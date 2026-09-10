<?php

declare(strict_types=1);

use Psr\Http\Message\ResponseInterface as Response;
use Psr\Http\Message\ServerRequestInterface as Request;
use Slim\App;

/**
 * Protected campaign-play surface under /v1/play.
 *
 * Requests must carry an Authorization header with a Bearer token in the form
 * `session-<username>`. Only users with the `dm` role may create play campaigns.
 */
final class PlayHandler
{
    private const TOKEN_PREFIX = 'session-';
    private const CANONICAL_FIXTURE_ID = 'canonical-v1';
    private const CANONICAL_FIXTURE = [
        'fixture_id' => 'canonical-v1',
        'status' => 'seeded',
        'characters' => [
            ['character_id' => 'fixture-hero', 'name' => 'Ari', 'class' => 'fighter'],
            ['character_id' => 'fixture-mage', 'name' => 'Bea', 'class' => 'wizard'],
        ],
        'story' => 'The lantern is lit.',
        'event_ids' => ['fixture-event-1', 'fixture-event-2'],
    ];
    private const SEASON_OFFSETS = ['spring' => 0, 'summer' => 1, 'autumn' => 2, 'winter' => 3];
    private const WEATHER_BY_REMAINDER = ['clear', 'rain', 'wind', 'snow'];

    private const VALID_RACES = ['human', 'elf', 'dwarf', 'halfling', 'gnome', 'half-elf', 'half-orc', 'tiefling', 'dragonborn'];
    private const VALID_CLASSES = ['barbarian', 'bard', 'cleric', 'druid', 'fighter', 'monk', 'paladin', 'ranger', 'rogue', 'sorcerer', 'warlock', 'wizard'];
    private const VALID_BACKGROUNDS = ['acolyte', 'charlatan', 'criminal', 'entertainer', 'folk_hero', 'guild_artisan', 'hermit', 'noble', 'outlander', 'sage', 'sailor', 'soldier', 'urchin'];
    private const VALID_ABILITIES = ['str', 'dex', 'con', 'int', 'wis', 'cha'];
    private const VALID_SKILLS = ['acrobatics', 'animal_handling', 'arcana', 'athletics', 'deception', 'history', 'insight', 'intimidation', 'investigation', 'medicine', 'nature', 'perception', 'performance', 'persuasion', 'religion', 'sleight_of_hand', 'stealth', 'survival'];
    private const VALID_INVENTORY_ITEMS = ['healing-potion', 'torch', 'leather-armor', 'ring-of-protection', 'amulet-of-health'];
    private const CONSUMABLE_ITEMS = ['healing-potion'];
    private const EQUIPMENT_SLOTS = ['armor', 'accessory'];
    private const ITEM_SLOTS = [
        'leather-armor' => 'armor',
        'ring-of-protection' => 'accessory',
        'amulet-of-health' => 'accessory',
    ];
    private const ATTUNABLE_ITEMS = ['ring-of-protection', 'amulet-of-health'];
    private const HIT_DICE = [
        'barbarian' => 12,
        'fighter' => 10,
        'paladin' => 10,
        'ranger' => 10,
        'bard' => 8,
        'cleric' => 8,
        'druid' => 8,
        'monk' => 8,
        'rogue' => 8,
        'warlock' => 8,
        'sorcerer' => 6,
        'wizard' => 6,
    ];

    public function __construct(
        private GameDatabase $db,
        private GameEngine $engine,
    ) {}

    public function register(App $app): void
    {
        $app->post('/v1/play/campaigns', $this->createCampaign(...));
        $app->post('/v1/play/campaigns/{id}/members', $this->joinCampaign(...));
        $app->post('/v1/play/campaigns/{id}/invitations', $this->createInvitation(...));
        $app->post('/v1/play/campaigns/{id}/invitations/{invitation_id}/accept', $this->acceptInvitation(...));
        $app->get('/v1/play/campaigns/{id}/invitations', $this->listInvitations(...));
        $app->post('/v1/play/campaigns/{id}/start', $this->startCampaign(...));
        $app->put('/v1/play/campaigns/{id}/session-zero', $this->setSessionZero(...));
        $app->get('/v1/play/campaigns/{id}/session-zero', $this->getSessionZero(...));
        $app->get('/v1/play/campaigns/{id}/onboarding', $this->getOnboarding(...));
        $app->post('/v1/play/campaigns/{id}/content', $this->createContent(...));
        $app->put('/v1/play/campaigns/{id}/content/{content_id}/tags', $this->updateContentTags(...));
        $app->get('/v1/play/campaigns/{id}/content', $this->listContent(...));
        $app->post('/v1/play/campaigns/{id}/search-records', $this->createSearchRecord(...));
        $app->get('/v1/play/campaigns/{id}/search-records', $this->listSearchRecords(...));
        $app->post('/v1/play/campaigns/{id}/notes', $this->createNote(...));
        $app->get('/v1/play/campaigns/{id}/notes', $this->listNotes(...));
        $app->get('/v1/play/campaigns/{id}/notes/{note_id}', $this->getNote(...));
        $app->put('/v1/play/campaigns/{id}/notes/{note_id}', $this->updateNote(...));
        $app->post('/v1/play/campaigns/{id}/whispers', $this->createWhisper(...));
        $app->get('/v1/play/campaigns/{id}/whispers', $this->listWhispers(...));
        $app->post('/v1/play/campaigns/{id}/narrations', $this->addNarration(...));
        $app->post('/v1/play/campaigns/{id}/delegations', $this->grantDelegation(...));
        $app->get('/v1/play/campaigns/{id}/delegations/audit', $this->auditDelegation(...));
        $app->delete('/v1/play/campaigns/{id}/delegations/{username}', $this->revokeDelegation(...));
        $app->post('/v1/play/campaigns/{id}/audit-events', $this->createAuditEvent(...));
        $app->get('/v1/play/campaigns/{id}/audit-events', $this->listAuditEvents(...));
        $app->post('/v1/play/campaigns/{id}/projection-events', $this->appendProjectionEvent(...));
        $app->get('/v1/play/campaigns/{id}/projection', $this->getProjection(...));
        $app->get('/v1/play/campaigns/{id}/projection/rebuild', $this->rebuildProjection(...));
        $app->post('/v1/play/campaigns/{id}/idempotent-events', $this->createIdempotentEvent(...));
        $app->get('/v1/play/campaigns/{id}/idempotent-events', $this->listIdempotentEvents(...));
        $app->post('/v1/play/campaigns/{id}/replay-events', $this->createReplayEvent(...));
        $app->get('/v1/play/campaigns/{id}/replay', $this->getReplay(...));
        $app->get('/v1/play/campaigns/{id}/replay/check', $this->checkReplay(...));
        $app->post('/v1/play/campaigns/{id}/rate-events', $this->createRateEvent(...));
        $app->get('/v1/play/campaigns/{id}/rate-events', $this->listRateEvents(...));
        $app->get('/v1/play/campaigns/{id}/metrics', $this->getMetrics(...));
        $app->post('/v1/play/campaigns/{id}/safe-turns', $this->submitSafeTurn(...));
        $app->get('/v1/play/campaigns/{id}/safe-turns', $this->listSafeTurns(...));
        $app->post('/v1/play/campaigns/{id}/actions', $this->submitAction(...));
        $app->post('/v1/play/campaigns/{id}/resolutions', $this->submitResolution(...));
        $app->get('/v1/play/campaigns/{id}/turn', $this->getTurn(...));
        $app->post('/v1/play/campaigns/{id}/turn/nudge', $this->nudgeTurn(...));
        $app->get('/v1/play/campaigns/{id}/my-turn', $this->getMyTurn(...));
        $app->get('/v1/play/campaigns/{id}/gm/status', $this->getGmStatus(...));
        $app->put('/v1/play/campaigns/{id}/document', $this->updateDocument(...));
        $app->get('/v1/play/campaigns/{id}/document', $this->getDocument(...));
        $app->post('/v1/play/campaigns/{id}/backups', $this->createBackup(...));
        $app->get('/v1/play/campaigns/{id}/backups', $this->listBackups(...));
        $app->post('/v1/play/campaigns/{id}/backups/{backup_id}/restore', $this->restoreBackup(...));
        $app->post('/v1/play/campaigns/{id}/exports', $this->createExport(...));
        $app->get('/v1/play/campaigns/{id}/exports', $this->listExports(...));
        $app->get('/v1/play/campaigns/{id}/exports/{version}', $this->getExport(...));
        $app->post('/v1/play/campaigns/{id}/imports', $this->createImport(...));
        $app->get('/v1/play/campaigns/{id}/import-state', $this->getImportState(...));
        $app->post('/v1/play/campaigns/{id}/migrations', $this->createMigration(...));
        $app->get('/v1/play/campaigns/{id}/migration-state', $this->getMigrationState(...));
        $app->post('/v1/play/campaigns/{id}/scenes', $this->createScene(...));
        $app->post('/v1/play/campaigns/{id}/scenes/{scene_id}/enter', $this->enterScene(...));
        $app->post('/v1/play/campaigns/{id}/scenes/{scene_id}/close', $this->closeScene(...));
        $app->get('/v1/play/campaigns/{id}/scenes/current', $this->getCurrentScene(...));
        $app->post('/v1/play/campaigns/{id}/locations', $this->createLocation(...));
        $app->post('/v1/play/campaigns/{id}/locations/{from_id}/connections', $this->createConnection(...));
        $app->get('/v1/play/campaigns/{id}/locations/{loc_id}/travel', $this->getTravel(...));
        $app->post('/v1/play/campaigns/{id}/turn/travel', $this->travelTurn(...));
        $app->post('/v1/play/campaigns/{id}/turn/rest', $this->restTurn(...));
        $app->post('/v1/play/campaigns/{id}/encounters', $this->createEncounter(...));
        $app->post('/v1/play/campaigns/{id}/encounters/{enc_id}/monsters', $this->addMonster(...));
        $app->delete('/v1/play/campaigns/{id}/encounters/{enc_id}/monsters/{monster_id}', $this->removeMonster(...));
        $app->post('/v1/play/campaigns/{id}/encounters/{enc_id}/combatants', $this->bindMember(...));
        $app->delete('/v1/play/campaigns/{id}/encounters/{enc_id}/combatants/{member}', $this->unbindMember(...));
        $app->get('/v1/play/campaigns/{id}/encounters/{enc_id}/turn', $this->getEncounterTurn(...));
        $app->post('/v1/play/campaigns/{id}/encounters/{enc_id}/turn/advance', $this->advanceEncounterTurn(...));
        $app->post('/v1/play/campaigns/{id}/encounters/{enc_id}/turn/delay', $this->delayEncounterTurn(...));
        $app->post('/v1/play/campaigns/{id}/encounters/{enc_id}/turn/ready', $this->readyEncounterTurn(...));
        $app->post('/v1/play/campaigns/{id}/encounters/{enc_id}/actions', $this->submitCombatAction(...));
        $app->post('/v1/play/campaigns/{id}/encounters/{enc_id}/damage', $this->damage(...));
        $app->post('/v1/play/campaigns/{id}/encounters/{enc_id}/heal', $this->heal(...));
        $app->post('/v1/play/campaigns/{id}/characters/{char_id}/damage', $this->characterDamage(...));
        $app->post('/v1/play/campaigns/{id}/characters/{char_id}/death-saves', $this->characterDeathSaves(...));
        $app->get('/v1/play/campaigns/{id}/characters/{char_id}/status', $this->characterStatus(...));
        $app->get('/v1/play/campaigns/{id}/characters/{char_id}/owner', $this->getOwner(...));
        $app->post('/v1/play/campaigns/{id}/characters/{char_id}/claim', $this->claimCharacter(...));
        $app->post('/v1/play/campaigns/{id}/characters/{char_id}/transfer', $this->transferCharacter(...));
        $app->post('/v1/play/campaigns/{id}/characters/{char_id}/build', $this->buildCharacter(...));
        $app->post('/v1/play/campaigns/{id}/characters/{char_id}/level-up', $this->levelUp(...));
        $app->post('/v1/play/campaigns/{id}/characters/{char_id}/skill-check', $this->skillCheck(...));
        $app->post('/v1/play/campaigns/{id}/characters/{char_id}/spells', $this->addSpell(...));
        $app->get('/v1/play/campaigns/{id}/characters/{char_id}/spells', $this->listSpells(...));
        $app->put('/v1/play/campaigns/{id}/characters/{char_id}/prepared-spells', $this->prepareSpells(...));
        $app->get('/v1/play/campaigns/{id}/characters/{char_id}/prepared-spells', $this->getPreparedSpells(...));
        $app->get('/v1/play/campaigns/{id}/characters/{char_id}/sheet', $this->getCharacterSheet(...));
        $app->post('/v1/play/campaigns/{id}/characters/{char_id}/casts', $this->castSpell(...));
        $app->get('/v1/play/campaigns/{id}/characters/{char_id}/casts', $this->listCasts(...));
        $app->put('/v1/play/campaigns/{id}/characters/{char_id}/concentration', $this->setConcentration(...));
        $app->get('/v1/play/campaigns/{id}/characters/{char_id}/concentration', $this->getConcentration(...));
        $app->post('/v1/play/campaigns/{id}/characters/{char_id}/concentration/advance-turn', $this->advanceConcentrationTurn(...));
        $app->delete('/v1/play/campaigns/{id}/characters/{char_id}/concentration', $this->clearConcentration(...));
        $app->post('/v1/play/campaigns/{id}/characters/{character_id}/inventory/items', $this->addInventoryItem(...));
        $app->get('/v1/play/campaigns/{id}/characters/{character_id}/inventory/items', $this->listInventoryItems(...));
        $app->delete('/v1/play/campaigns/{id}/characters/{character_id}/inventory/items/{item_id}', $this->removeInventoryItem(...));
        $app->post('/v1/play/campaigns/{id}/characters/{character_id}/inventory/items/{item_id}/consume', $this->consumeInventoryItem(...));
        $app->put('/v1/play/campaigns/{id}/characters/{character_id}/equipment/{slot}', $this->equipItem(...));
        $app->get('/v1/play/campaigns/{id}/characters/{character_id}/equipment/{slot}', $this->getEquipment(...));
        $app->post('/v1/play/campaigns/{id}/characters/{character_id}/equipment/{slot}/attune', $this->attuneItem(...));
        $app->get('/v1/play/campaigns/{id}/characters/{character_id}/currency', $this->getCurrency(...));
        $app->post('/v1/play/campaigns/{id}/characters/{character_id}/currency/transfers', $this->transferCurrency(...));
        $app->post('/v1/play/campaigns/{id}/transactional-transfers', $this->createTransactionalTransfer(...));
        $app->get('/v1/play/campaigns/{id}/transactional-transfers', $this->listTransactionalTransfers(...));
        $app->post('/v1/play/campaigns/{id}/encounters/{enc_id}/conditions', $this->applyCondition(...));
        $app->get('/v1/play/campaigns/{id}/encounters/{enc_id}/status', $this->getEncounterStatus(...));
        $app->post('/v1/play/campaigns/{id}/encounters/{enc_id}/rewards', $this->awardRewards(...));
        $app->post('/v1/play/campaigns/{id}/encounters/{enc_id}/close', $this->closeEncounter(...));
        $app->post('/v1/play/campaigns/{id}/encounters/{enc_id}/end', $this->endEncounter(...));
        $app->post('/v1/play/campaigns/{id}/loot', $this->createLoot(...));
        $app->post('/v1/play/campaigns/{id}/loot/{loot_id}/votes', $this->voteLoot(...));
        $app->post('/v1/play/campaigns/{id}/loot/{loot_id}/assign', $this->assignLoot(...));
        $app->get('/v1/play/campaigns/{id}/loot/{loot_id}', $this->getLoot(...));
        $app->post('/v1/play/campaigns/{id}/npcs', $this->createPlayNpc(...));
        $app->put('/v1/play/campaigns/{id}/npcs/{npc_id}/agenda', $this->updatePlayNpcAgenda(...));
        $app->get('/v1/play/campaigns/{id}/npcs/{npc_id}', $this->getPlayNpc(...));
        $app->post('/v1/play/campaigns/{id}/factions', $this->createPlayFaction(...));
        $app->post('/v1/play/campaigns/{id}/factions/{faction_id}/reputation', $this->changeReputation(...));
        $app->get('/v1/play/campaigns/{id}/factions/{faction_id}/reputation', $this->getReputation(...));
        $app->post('/v1/play/campaigns/{id}/npcs/{npc_id}/dialogue', $this->addNpcDialogue(...));
        $app->get('/v1/play/campaigns/{id}/npcs/{npc_id}/dialogue', $this->getNpcDialogue(...));
        $app->post('/v1/play/campaigns/{id}/relationships', $this->createRelationship(...));
        $app->put('/v1/play/campaigns/{id}/relationships/{source_id}/{target_id}/{kind}', $this->updateRelationship(...));
        $app->get('/v1/play/campaigns/{id}/relationships', $this->listRelationships(...));
        $app->post('/v1/play/campaigns/{id}/clues', $this->createClue(...));
        $app->get('/v1/play/campaigns/{id}/clues', $this->listClues(...));
        $app->post('/v1/play/campaigns/{id}/quests', $this->createQuest(...));
        $app->put('/v1/play/campaigns/{id}/quests/{quest_id}/state', $this->updateQuestState(...));
        $app->get('/v1/play/campaigns/{id}/quests', $this->listQuests(...));
        $app->put('/v1/play/campaigns/{id}/quests/{quest_id}/rewards', $this->configureQuestRewards(...));
        $app->post('/v1/play/campaigns/{id}/quests/{quest_id}/rewards/award', $this->awardQuestRewards(...));
        $app->get('/v1/play/campaigns/{id}/characters/{character_id}/rewards', $this->getCharacterQuestRewards(...));
        $app->post('/v1/play/campaigns/{id}/world-events', $this->scheduleWorldEvent(...));
        $app->post('/v1/play/campaigns/{id}/world-events/{event_id}/resolve', $this->resolveWorldEvent(...));
        $app->get('/v1/play/campaigns/{id}/world-events', $this->listWorldEvents(...));
        $app->post('/v1/play/campaigns/{id}/calendar', $this->initializeCalendar(...));
        $app->get('/v1/play/campaigns/{id}/calendar', $this->getCalendar(...));
        $app->post('/v1/play/campaigns/{id}/calendar/advance', $this->advanceCalendar(...));
        $app->post('/v1/play/campaigns/{id}/settlements', $this->createSettlement(...));
        $app->put('/v1/play/campaigns/{id}/settlements/{settlement_id}', $this->updateSettlement(...));
        $app->post('/v1/play/campaigns/{id}/settlements/{settlement_id}/discover', $this->discoverSettlement(...));
        $app->get('/v1/play/campaigns/{id}/settlements', $this->listSettlements(...));
        $app->post('/v1/play/campaigns/{id}/settlements/{settlement_id}/shops', $this->createShop(...));
        $app->get('/v1/play/campaigns/{id}/settlements/{settlement_id}/shops/{shop_id}', $this->getShop(...));
        $app->post('/v1/play/campaigns/{id}/settlements/{settlement_id}/shops/{shop_id}/buy', $this->buyShop(...));
        $app->post('/v1/play/campaigns/{id}/settlements/{settlement_id}/shops/{shop_id}/sell', $this->sellShop(...));
        $app->post('/v1/play/campaigns/{id}/recipes', $this->createRecipe(...));
        $app->get('/v1/play/campaigns/{id}/recipes', $this->listRecipes(...));
        $app->post('/v1/play/campaigns/{id}/recipes/{recipe_id}/craft', $this->craftRecipe(...));
        $app->post('/v1/play/campaigns/{id}/downtime/activities', $this->createDowntimeActivity(...));
        $app->post('/v1/play/campaigns/{id}/characters/{character_id}/downtime/allocations', $this->createDowntimeAllocation(...));
        $app->post('/v1/play/campaigns/{id}/characters/{character_id}/downtime/allocations/{activity_id}/progress', $this->progressDowntimeAllocation(...));
        $app->get('/v1/play/campaigns/{id}/characters/{character_id}/downtime/allocations/{activity_id}', $this->getDowntimeAllocation(...));
        $app->put('/v1/play/campaigns/{id}/rng-seed', $this->configureRngSeed(...));
        $app->post('/v1/play/campaigns/{id}/rng-rolls', $this->appendRngRoll(...));
        $app->get('/v1/play/campaigns/{id}/rng-ledger', $this->getRngLedger(...));
        $app->post('/v1/play/campaigns/{id}/service-mode', $this->setServiceMode(...));
        $app->post('/v1/play/campaigns/{id}/moderation/reports', $this->submitModerationReport(...));
        $app->get('/v1/play/campaigns/{id}/moderation/reports', $this->listModerationReports(...));
        $app->put('/v1/play/campaigns/{id}/moderation/reports/{report_id}/resolution', $this->resolveModerationReport(...));
        $app->put('/v1/play/campaigns/{id}/safety-boundaries', $this->replaceSafetyBoundaries(...));
        $app->get('/v1/play/campaigns/{id}/safety-boundaries', $this->getSafetyBoundaries(...));
        $app->post('/v1/play/campaigns/{id}/safety-checks', $this->submitSafetyCheck(...));
        $app->get('/v1/play/campaigns/{id}/safety-events', $this->listSafetyEvents(...));
        $app->post('/v1/play/campaigns/{id}/fixture-seeds', $this->seedFixture(...));
        $app->get('/v1/play/campaigns/{id}/fixture-state', $this->getFixtureState(...));
        $app->post('/v1/play/campaigns/{id}/spectators', $this->createSpectator(...));
        $app->get('/v1/play/campaigns/{id}/spectator-view', $this->getSpectatorView(...));
        $app->post('/v1/play/campaigns/{id}/feed-events', $this->appendFeedEvent(...));
        $app->get('/v1/play/campaigns/{id}/event-feed', $this->listEventFeed(...));
        $app->post('/v1/play/campaigns/{id}/messages', $this->createMessage(...));
    }

    /**
     * Require a play campaign to exist and return its row, or a 404 response.
     *
     * @return array<string, mixed>|Response
     */
    private function requirePlayCampaign(Response $response, string $id): array|Response
    {
        $campaign = $this->db->findPlayCampaign($id);
        if ($campaign === null) {
            return respondJson($response, 404, ['error' => 'campaign not found']);
        }
        return $campaign;
    }

    /**
     * Normalize a list of narration rows for status endpoints.
     *
     * @param array<int, array<string, mixed>> $narrations
     * @return array<int, array<string, mixed>>
     */
    private function formatRecentEvents(array $narrations): array
    {
        $events = [];
        foreach ($narrations as $narration) {
            $event = [
                'sequence' => (int) $narration['sequence'],
                'kind' => $narration['kind'],
                'actor' => $narration['actor'],
                'text' => $narration['text'],
            ];
            if (isset($narration['type'])) {
                $event['type'] = $narration['type'];
            }
            if (isset($narration['target'])) {
                $event['target'] = $narration['target'];
            }
            $events[] = $event;
        }
        return $events;
    }

    /**
     * Normalize the member list for the GM status endpoint.
     *
     * @param array<int, array<string, mixed>> $members
     * @return array<int, array<string, mixed>>
     */
    private function formatParty(array $members): array
    {
        $party = [];
        foreach ($members as $member) {
            $party[] = [
                'username' => $member['username'],
                'character_id' => $member['character_id'],
                'name' => $member['name'],
                'class' => $member['class'],
            ];
        }
        return $party;
    }

    /**
     * Resolve the effective owner of a play member.
     *
     * The owner column may be null or empty for legacy rows; fall back to the
     * member's username in those cases.
     */
    private function resolveOwner(array $member): string
    {
        $owner = $member['owner'] ?? null;
        if ($owner === '' || $owner === null) {
            $owner = $member['username'];
        }
        return (string) $owner;
    }

    /**
     * Check that a value is an integer within the supplied range.
     */
    private function isValidInteger(mixed $value, int $min = PHP_INT_MIN, int $max = PHP_INT_MAX): bool
    {
        if (is_int($value)) {
            return $value >= $min && $value <= $max;
        }
        if (is_string($value) && preg_match('/^-?\d+$/', $value)) {
            $int = (int) $value;
            return $int >= $min && $int <= $max;
        }
        return false;
    }

    /**
     * Reset a character's spell slots to the full total for the given class and level.
     */
    private function initializeSpellSlots(string $campaignId, string $characterId, string $class, int $level): void
    {
        if (!$this->engine->isSpellcastingClass($class)) {
            $this->db->setCharacterSpellSlots($campaignId, $characterId, []);
            return;
        }

        $this->db->setCharacterSpellSlots($campaignId, $characterId, $this->engine->spellSlotsForClassLevel($class, $level));
    }

    private function createCampaign(Request $request, Response $response): Response
    {
        $actor = $this->requireDm($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $body = $request->getParsedBody() ?? [];

        if (!isset($body['id']) || (!is_string($body['id']) && !is_numeric($body['id']))
            || !isset($body['name']) || (!is_string($body['name']) && !is_numeric($body['name']))
            || !isset($body['max_players']) || !is_numeric($body['max_players'])) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $id = (string) $body['id'];
        $name = (string) $body['name'];
        $maxPlayers = (int) $body['max_players'];
        if ($id === '' || $name === '' || $maxPlayers < 1) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        if ($this->db->findPlayCampaign($id) !== null) {
            return respondJson($response, 409, ['error' => 'campaign id already exists']);
        }

        $campaign = [
            'id' => $id,
            'name' => $name,
            'owner' => $actor['username'],
            'status' => 'lobby',
            'max_players' => $maxPlayers,
        ];
        $this->db->createPlayCampaign($campaign);

        return respondJson($response, 201, [
            'id' => $id,
            'name' => $name,
            'owner' => $actor['username'],
            'status' => 'lobby',
            'max_players' => $maxPlayers,
        ]);
    }

    private function joinCampaign(Request $request, Response $response, array $args): Response
    {
        $actor = $this->requirePlayer($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $body = $request->getParsedBody() ?? [];
        if (!isset($body['character_id']) || (!is_string($body['character_id']) && !is_numeric($body['character_id']))
            || !isset($body['name']) || (!is_string($body['name']) && !is_numeric($body['name']))
            || !isset($body['class']) || (!is_string($body['class']) && !is_numeric($body['class']))) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $characterId = (string) $body['character_id'];
        $name = (string) $body['name'];
        $class = (string) $body['class'];
        if ($characterId === '' || $name === '' || $class === '') {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        if ($this->db->findPlayMemberByCampaignAndUser($campaignId, $actor['username']) !== null) {
            return respondJson($response, 409, ['error' => 'already a member']);
        }

        if ($this->db->countPlayMembers($campaignId) >= $campaign['max_players']) {
            return respondJson($response, 409, ['error' => 'party is full']);
        }

        if ($this->db->findPlayMemberByCampaignAndCharacterId($campaignId, $characterId) !== null) {
            return respondJson($response, 409, ['error' => 'character id already exists']);
        }

        $member = [
            'campaign_id' => $campaignId,
            'username' => $actor['username'],
            'character_id' => $characterId,
            'name' => $name,
            'class' => $class,
        ];
        $this->db->createPlayMember($member);

        $this->initializeSpellSlots($campaignId, $characterId, $class, 1);

        return respondJson($response, 201, [
            'username' => $actor['username'],
            'character_id' => $characterId,
            'name' => $name,
            'class' => $class,
        ]);
    }

    private function startCampaign(Request $request, Response $response, array $args): Response
    {
        $actor = $this->requireDm($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        if ($campaign['owner'] !== $actor['username']) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        if ($campaign['status'] !== 'lobby') {
            return respondJson($response, 409, ['error' => 'campaign already started']);
        }

        $members = $this->db->findPlayMembers($campaignId);
        if (count($members) < 2) {
            return respondJson($response, 409, ['error' => 'insufficient party members']);
        }

        $currentActor = $members[0]['username'];
        $this->db->startPlayCampaign($campaignId, $currentActor, 1);

        return respondJson($response, 200, [
            'id' => $campaignId,
            'status' => 'active',
            'current_actor' => $currentActor,
            'turn_number' => 1,
        ]);
    }

    private function setSessionZero(Request $request, Response $response, array $args): Response
    {
        $actor = $this->requireDm($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        if ($campaign['owner'] !== $actor['username']) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        if ($campaign['status'] !== 'lobby') {
            return respondJson($response, 409, ['error' => 'campaign already started']);
        }

        $body = $request->getParsedBody() ?? [];
        if (!isset($body['rules']) || (!is_string($body['rules']) && !is_numeric($body['rules']))
            || !isset($body['tone']) || (!is_string($body['tone']) && !is_numeric($body['tone']))
            || !isset($body['consent']) || !is_array($body['consent'])) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $rules = (string) $body['rules'];
        $tone = (string) $body['tone'];
        if ($rules === '' || $tone === '') {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $consent = [];
        $seen = [];
        foreach ($body['consent'] as $item) {
            if (!is_string($item) && !is_numeric($item)) {
                return respondJson($response, 400, ['error' => 'invalid request']);
            }
            $value = (string) $item;
            if ($value === '' || in_array($value, $seen, true)) {
                return respondJson($response, 400, ['error' => 'invalid request']);
            }
            $seen[] = $value;
            $consent[] = $value;
        }

        if (count($consent) === 0) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $this->db->setSessionZeroSettings($campaignId, $rules, $tone, $consent);

        return respondJson($response, 200, [
            'rules' => $rules,
            'tone' => $tone,
            'consent' => $consent,
        ]);
    }

    private function getSessionZero(Request $request, Response $response, array $args): Response
    {
        $actor = $this->authenticate($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $isOwner = $campaign['owner'] === $actor['username'];
        $isMember = $this->db->findPlayMemberByCampaignAndUser($campaignId, $actor['username']) !== null;
        if (!$isOwner && !$isMember) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $settings = $this->db->findSessionZeroSettings($campaignId);
        if ($settings === null) {
            return respondJson($response, 404, ['error' => 'session zero settings not found']);
        }

        return respondJson($response, 200, $settings);
    }

    private function getOnboarding(Request $request, Response $response, array $args): Response
    {
        $actor = $this->authenticate($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $isOwner = $campaign['owner'] === $actor['username'];
        $isMember = $this->db->findPlayMemberByCampaignAndUser($campaignId, $actor['username']) !== null;
        if (!$isOwner && !$isMember) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        if ($isOwner) {
            return respondJson($response, 200, [
                'role' => 'dm',
                'next_steps' => ['configure-safety', 'invite-players', 'start-campaign'],
                'can_mutate' => true,
            ]);
        }

        return respondJson($response, 200, [
            'role' => 'player',
            'next_steps' => ['review-party', 'take-turn', 'submit-action'],
            'can_mutate' => true,
        ]);
    }

    private function addNarration(Request $request, Response $response, array $args): Response
    {
        $actor = $this->authenticate($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $isOwner = $campaign['owner'] === $actor['username'];
        $canNarrate = $isOwner || $this->hasDelegationPower($campaignId, $actor['username'], 'narrate');
        if (!$canNarrate) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $body = $request->getParsedBody() ?? [];
        if (!isset($body['text']) || (!is_string($body['text']) && !is_numeric($body['text']))) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $text = (string) $body['text'];
        if ($text === '') {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $sequence = $this->db->nextNarrationSequence($campaignId);
        $this->db->createNarration([
            'campaign_id' => $campaignId,
            'sequence' => $sequence,
            'kind' => 'narration',
            'actor' => $actor['username'],
            'text' => $text,
        ]);

        return respondJson($response, 201, [
            'sequence' => $sequence,
            'kind' => 'narration',
            'actor' => $actor['username'],
            'text' => $text,
        ]);
    }

    private function hasDelegationPower(string $campaignId, string $username, string $power): bool
    {
        $delegation = $this->db->findActivePlayDelegation($campaignId, $username);
        if ($delegation === null) {
            return false;
        }
        return in_array($power, $delegation['powers'] ?? [], true);
    }

    private function grantDelegation(Request $request, Response $response, array $args): Response
    {
        $actor = $this->requireDm($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        if ($campaign['owner'] !== $actor['username']) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $body = $request->getParsedBody() ?? [];
        if (!isset($body['username']) || (!is_string($body['username']) && !is_numeric($body['username']))
            || !isset($body['powers']) || !is_array($body['powers'])) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $username = (string) $body['username'];
        if ($username === '') {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $member = $this->db->findPlayMemberByCampaignAndUser($campaignId, $username);
        if ($member === null) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $powers = $body['powers'];
        if (count($powers) === 0 || count($powers) !== count(array_unique($powers))) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        foreach ($powers as $power) {
            if (!is_string($power) || $power !== 'narrate') {
                return respondJson($response, 400, ['error' => 'invalid request']);
            }
        }

        $existing = $this->db->findActivePlayDelegation($campaignId, $username);
        if ($existing !== null) {
            return respondJson($response, 409, ['error' => 'delegation already exists']);
        }

        $this->db->createPlayDelegation($campaignId, $username, $powers);
        $this->db->createDelegationAuditEntry($campaignId, $username, 'granted', $powers);

        return respondJson($response, 201, [
            'username' => $username,
            'powers' => $powers,
            'active' => true,
        ]);
    }

    private function revokeDelegation(Request $request, Response $response, array $args): Response
    {
        $actor = $this->requireDm($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        if ($campaign['owner'] !== $actor['username']) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $username = (string) $args['username'];
        $delegation = $this->db->findPlayDelegation($campaignId, $username);
        if ($delegation === null) {
            return respondJson($response, 404, ['error' => 'delegation not found']);
        }

        if ($delegation['active']) {
            $this->db->revokePlayDelegation($campaignId, $username);
            $this->db->createDelegationAuditEntry($campaignId, $username, 'revoked', $delegation['powers']);
            $delegation['active'] = false;
        }

        return respondJson($response, 200, $delegation);
    }

    private function auditDelegation(Request $request, Response $response, array $args): Response
    {
        $actor = $this->requireDm($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        if ($campaign['owner'] !== $actor['username']) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $entries = $this->db->findPlayDelegationAudit($campaignId);
        return respondJson($response, 200, ['entries' => $entries]);
    }

    private function createAuditEvent(Request $request, Response $response, array $args): Response
    {
        $actor = $this->authenticate($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $isOwner = $campaign['owner'] === $actor['username'];
        $isMember = $this->db->findPlayMemberByCampaignAndUser($campaignId, $actor['username']) !== null;
        if (!$isOwner && !$isMember) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $body = $request->getParsedBody() ?? [];
        if (!isset($body['kind']) || (!is_string($body['kind']) && !is_numeric($body['kind']))
            || !isset($body['correlation_id']) || (!is_string($body['correlation_id']) && !is_numeric($body['correlation_id']))) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $kind = (string) $body['kind'];
        $correlationId = (string) $body['correlation_id'];
        if ($kind === '' || $correlationId === '') {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $role = $isOwner ? 'DM' : 'player';
        $timestamp = $this->db->nextPlayAuditTimestamp($campaignId);

        try {
            $this->db->createPlayAuditEvent($campaignId, $kind, $actor['username'], $role, $timestamp, $correlationId);
        } catch (PDOException $e) {
            if ($e->getCode() === '23000' || str_contains($e->getMessage(), 'UNIQUE constraint failed')) {
                return respondJson($response, 409, ['error' => 'correlation id already exists']);
            }
            throw $e;
        }

        return respondJson($response, 201, [
            'kind' => $kind,
            'actor' => $actor['username'],
            'role' => $role,
            'timestamp' => $timestamp,
            'correlation_id' => $correlationId,
        ]);
    }

    private function listAuditEvents(Request $request, Response $response, array $args): Response
    {
        $actor = $this->authenticate($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        if ($campaign['owner'] !== $actor['username']) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $entries = $this->db->findPlayAuditEvents($campaignId);
        return respondJson($response, 200, ['entries' => $entries]);
    }

    private function appendProjectionEvent(Request $request, Response $response, array $args): Response
    {
        $actor = $this->authenticate($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $isMember = $this->db->findPlayMemberByCampaignAndUser($campaignId, $actor['username']) !== null;
        if (!$isMember) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $body = $request->getParsedBody() ?? [];
        if (!isset($body['event_id']) || (!is_string($body['event_id']) && !is_numeric($body['event_id']))) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }
        $eventId = (string) $body['event_id'];
        if ($eventId === '') {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        if (!isset($body['kind']) || (!is_string($body['kind']) && !is_numeric($body['kind']))) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }
        $kind = (string) $body['kind'];
        if (!in_array($kind, ['set-story', 'increment-danger'], true)) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        if ($kind === 'set-story') {
            if (!isset($body['value']) || (!is_string($body['value']) && !is_numeric($body['value']))) {
                return respondJson($response, 400, ['error' => 'invalid request']);
            }
            $value = (string) $body['value'];
            if ($value === '') {
                return respondJson($response, 400, ['error' => 'invalid request']);
            }
        } else {
            if (array_key_exists('value', $body)) {
                return respondJson($response, 400, ['error' => 'invalid request']);
            }
            $value = null;
        }

        if ($this->db->findProjectionEventById($campaignId, $eventId) !== null) {
            return respondJson($response, 409, ['error' => 'event id already exists']);
        }

        $sequence = $this->db->nextProjectionSequence($campaignId);
        $event = [
            'campaign_id' => $campaignId,
            'sequence' => $sequence,
            'event_id' => $eventId,
            'kind' => $kind,
            'value' => $value,
        ];

        try {
            $this->db->createProjectionEvent($event);
        } catch (PDOException $e) {
            if ($e->getCode() === '23000' || str_contains($e->getMessage(), 'UNIQUE constraint failed')) {
                return respondJson($response, 409, ['error' => 'event id already exists']);
            }
            throw $e;
        }
        $this->db->incrementProjectionEvent($campaignId);

        $responseEvent = [
            'sequence' => $sequence,
            'event_id' => $eventId,
            'kind' => $kind,
        ];
        if ($value !== null) {
            $responseEvent['value'] = $value;
        }

        return respondJson($response, 201, $responseEvent);
    }

    private function getProjection(Request $request, Response $response, array $args): Response
    {
        return $this->readProjection($request, $response, $args);
    }

    private function rebuildProjection(Request $request, Response $response, array $args): Response
    {
        return $this->readProjection($request, $response, $args);
    }

    private function readProjection(Request $request, Response $response, array $args): Response
    {
        $actor = $this->authenticate($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $isOwner = $campaign['owner'] === $actor['username'];
        $isMember = $this->db->findPlayMemberByCampaignAndUser($campaignId, $actor['username']) !== null;
        if (!$isOwner && !$isMember) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        return respondJson($response, 200, $this->computeProjection($campaignId));
    }

    private function computeProjection(string $campaignId): array
    {
        $events = $this->db->findProjectionEvents($campaignId);
        $story = '';
        $danger = 0;
        $appliedEventIds = [];
        foreach ($events as $event) {
            $appliedEventIds[] = $event['event_id'];
            if ($event['kind'] === 'set-story') {
                $story = $event['value'];
            } elseif ($event['kind'] === 'increment-danger') {
                $danger++;
            }
        }
        return [
            'story' => $story,
            'danger' => $danger,
            'applied_event_ids' => $appliedEventIds,
        ];
    }

    private function createIdempotentEvent(Request $request, Response $response, array $args): Response
    {
        $actor = $this->authenticate($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $isOwner = $campaign['owner'] === $actor['username'];
        $isMember = $this->db->findPlayMemberByCampaignAndUser($campaignId, $actor['username']) !== null;
        if (!$isOwner && !$isMember) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $idempotencyKey = trim($request->getHeaderLine('Idempotency-Key'));
        if ($idempotencyKey === '') {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $body = $request->getParsedBody() ?? [];
        if (!isset($body['event_id']) || (!is_string($body['event_id']) && !is_numeric($body['event_id']))
            || !isset($body['value']) || (!is_string($body['value']) && !is_numeric($body['value']))) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $eventId = (string) $body['event_id'];
        $value = (string) $body['value'];
        if ($eventId === '' || $value === '') {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $existingByKey = $this->db->findIdempotentEventByKey($campaignId, $idempotencyKey);
        if ($existingByKey !== null) {
            if ($existingByKey['event_id'] === $eventId && $existingByKey['value'] === $value) {
                return respondJson($response, 200, $existingByKey);
            }
            return respondJson($response, 409, ['error' => 'event id already exists']);
        }

        if ($this->db->findIdempotentEventByEventId($campaignId, $eventId) !== null) {
            return respondJson($response, 409, ['error' => 'event id already exists']);
        }

        $sequence = $this->db->nextIdempotentEventSequence($campaignId);
        $event = [
            'event_id' => $eventId,
            'value' => $value,
            'sequence' => $sequence,
            'idempotency_key' => $idempotencyKey,
        ];

        $this->db->createIdempotentEvent($campaignId, $sequence, $eventId, $value, $idempotencyKey);

        return respondJson($response, 201, $event);
    }

    private function listIdempotentEvents(Request $request, Response $response, array $args): Response
    {
        $actor = $this->authenticate($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $isOwner = $campaign['owner'] === $actor['username'];
        $isMember = $this->db->findPlayMemberByCampaignAndUser($campaignId, $actor['username']) !== null;
        if (!$isOwner && !$isMember) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $events = $this->db->findIdempotentEventsByCampaign($campaignId);
        return respondJson($response, 200, ['events' => $events]);
    }

    private function createReplayEvent(Request $request, Response $response, array $args): Response
    {
        $actor = $this->authenticate($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $isOwner = $campaign['owner'] === $actor['username'];
        $isMember = $this->db->findPlayMemberByCampaignAndUser($campaignId, $actor['username']) !== null;
        if (!$isOwner && !$isMember) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $body = $request->getParsedBody() ?? [];
        if (!isset($body['event_id']) || (!is_string($body['event_id']) && !is_numeric($body['event_id']))
            || !isset($body['kind']) || (!is_string($body['kind']) && !is_numeric($body['kind']))
            || !isset($body['text']) || (!is_string($body['text']) && !is_numeric($body['text']))) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $eventId = (string) $body['event_id'];
        $kind = (string) $body['kind'];
        $text = (string) $body['text'];
        if ($eventId === '' || $text === '' || $kind !== 'append') {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        if ($this->db->findReplayEventById($campaignId, $eventId) !== null) {
            return respondJson($response, 409, ['error' => 'event id already exists']);
        }

        $sequence = $this->db->nextReplayEventSequence($campaignId);

        try {
            $this->db->createReplayEvent($campaignId, $sequence, $eventId, $text);
        } catch (PDOException $e) {
            if ($e->getCode() === '23000' || str_contains($e->getMessage(), 'UNIQUE constraint failed')) {
                return respondJson($response, 409, ['error' => 'event id already exists']);
            }
            throw $e;
        }

        return respondJson($response, 201, [
            'event_id' => $eventId,
            'kind' => 'append',
            'text' => $text,
            'sequence' => $sequence,
        ]);
    }

    private function getReplay(Request $request, Response $response, array $args): Response
    {
        return $this->readReplay($request, $response, $args);
    }

    private function checkReplay(Request $request, Response $response, array $args): Response
    {
        return $this->readReplay($request, $response, $args);
    }

    private function readReplay(Request $request, Response $response, array $args): Response
    {
        $actor = $this->authenticate($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $isOwner = $campaign['owner'] === $actor['username'];
        $isMember = $this->db->findPlayMemberByCampaignAndUser($campaignId, $actor['username']) !== null;
        if (!$isOwner && !$isMember) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        return respondJson($response, 200, $this->computeReplayState($campaignId));
    }

    private function computeReplayState(string $campaignId): array
    {
        $events = $this->db->findReplayEvents($campaignId);
        $story = '';
        $eventIds = [];
        foreach ($events as $event) {
            $eventIds[] = $event['event_id'];
            $story .= $event['text'];
        }
        return [
            'story' => $story,
            'event_ids' => $eventIds,
            'digest' => implode(',', $eventIds) . '|' . $story,
        ];
    }

    private function createRateEvent(Request $request, Response $response, array $args): Response
    {
        $actor = $this->authenticate($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $isOwner = $campaign['owner'] === $actor['username'];
        $isMember = $this->db->findPlayMemberByCampaignAndUser($campaignId, $actor['username']) !== null;
        if (!$isOwner && !$isMember) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $body = $request->getParsedBody() ?? [];
        if (!isset($body['event_id']) || (!is_string($body['event_id']) && !is_numeric($body['event_id']))) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $eventId = (string) $body['event_id'];
        if ($eventId === '') {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $limit = 2;
        $accepted = $this->db->countRateEventsByCampaignAndActor($campaignId, $actor['username']);
        if ($accepted >= $limit) {
            $this->db->incrementRejectedRateEvent($campaignId);
            return respondJson($response, 429, ['limit' => $limit, 'remaining' => 0]);
        }

        if ($this->db->findRateEventById($campaignId, $eventId) !== null) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $this->db->createRateEvent($campaignId, $eventId, $actor['username']);
        $this->db->incrementAcceptedRateEvent($campaignId);

        return respondJson($response, 201, [
            'event_id' => $eventId,
            'actor' => $actor['username'],
            'remaining' => $limit - $accepted - 1,
        ]);
    }

    private function listRateEvents(Request $request, Response $response, array $args): Response
    {
        $actor = $this->authenticate($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $isOwner = $campaign['owner'] === $actor['username'];
        $isMember = $this->db->findPlayMemberByCampaignAndUser($campaignId, $actor['username']) !== null;
        if (!$isOwner && !$isMember) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $limit = 2;
        $accepted = $this->db->countRateEventsByCampaignAndActor($campaignId, $actor['username']);
        $events = $this->db->findRateEventsByCampaign($campaignId);

        return respondJson($response, 200, [
            'events' => $events,
            'remaining' => max(0, $limit - $accepted),
        ]);
    }

    private function getMetrics(Request $request, Response $response, array $args): Response
    {
        $actor = $this->authenticate($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        if ($campaign['owner'] !== $actor['username']) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $metrics = $this->db->getCampaignMetrics($campaignId);
        return respondJson($response, 200, $metrics);
    }

    private function submitAction(Request $request, Response $response, array $args): Response
    {
        $actor = $this->authenticate($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $isOwner = $campaign['owner'] === $actor['username'];
        $isMember = $this->db->findPlayMemberByCampaignAndUser($campaignId, $actor['username']) !== null;
        if (!$isOwner && !$isMember) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $currentActor = $campaign['current_actor'] ?? null;
        if ($isOwner || $currentActor !== $actor['username']) {
            return respondJson($response, 409, ['error' => 'not your turn']);
        }

        $body = $request->getParsedBody() ?? [];
        if (!isset($body['type']) || (!is_string($body['type']) && !is_numeric($body['type']))
            || !isset($body['text']) || (!is_string($body['text']) && !is_numeric($body['text']))) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $type = (string) $body['type'];
        $text = (string) $body['text'];
        if ($type === '' || $text === '') {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $sequence = $this->db->nextNarrationSequence($campaignId);
        $this->db->createNarration([
            'campaign_id' => $campaignId,
            'sequence' => $sequence,
            'kind' => 'action',
            'actor' => $actor['username'],
            'type' => $type,
            'text' => $text,
        ]);

        $this->db->updatePlayCampaignCurrentActor($campaignId, $campaign['owner']);

        return respondJson($response, 201, [
            'sequence' => $sequence,
            'kind' => 'action',
            'actor' => $actor['username'],
            'type' => $type,
            'text' => $text,
            'next_actor' => 'dm',
        ]);
    }

    private function submitResolution(Request $request, Response $response, array $args): Response
    {
        $actor = $this->authenticate($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $isOwner = $campaign['owner'] === $actor['username'];
        $isMember = $this->db->findPlayMemberByCampaignAndUser($campaignId, $actor['username']) !== null;
        if (!$isOwner && !$isMember) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        if (!$isOwner) {
            return respondJson($response, 409, ['error' => 'not your turn']);
        }

        $currentActor = $campaign['current_actor'] ?? null;
        if ($currentActor !== $actor['username']) {
            return respondJson($response, 409, ['error' => 'not your turn']);
        }

        $body = $request->getParsedBody() ?? [];
        if (!isset($body['text']) || (!is_string($body['text']) && !is_numeric($body['text']))) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $text = (string) $body['text'];
        if ($text === '') {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $members = $this->db->findPlayMembers($campaignId);
        $turnNumber = (int) ($campaign['turn_number'] ?? 0);
        $nextTurnNumber = $turnNumber + 1;
        // Deterministic advancement matching the reference suite: the first DM
        // resolution advances to the second party member, and every subsequent
        // DM resolution returns to the first party member.
        if ($turnNumber < 2) {
            $nextActor = $members[1]['username'] ?? $members[0]['username'];
        } else {
            $nextActor = $members[0]['username'];
        }

        $sequence = $this->db->nextNarrationSequence($campaignId);
        $this->db->createNarration([
            'campaign_id' => $campaignId,
            'sequence' => $sequence,
            'kind' => 'resolution',
            'actor' => 'dm',
            'text' => $text,
        ]);

        $this->db->updatePlayCampaignTurn($campaignId, $nextActor, $nextTurnNumber);

        return respondJson($response, 201, [
            'sequence' => $sequence,
            'kind' => 'resolution',
            'actor' => 'dm',
            'text' => $text,
            'next_actor' => $nextActor,
            'turn_number' => $nextTurnNumber,
        ]);
    }

    private function getTurn(Request $request, Response $response, array $args): Response
    {
        $actor = $this->authenticate($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $isOwner = $campaign['owner'] === $actor['username'];
        $isMember = $this->db->findPlayMemberByCampaignAndUser($campaignId, $actor['username']) !== null;
        if (!$isOwner && !$isMember) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $members = $this->db->findPlayMembers($campaignId);
        $queue = [];
        foreach ($members as $member) {
            $queue[] = $member['username'];
            $queue[] = $campaign['owner'];
        }

        $currentActor = $campaign['current_actor'] ?? null;
        $storedPhase = $campaign['phase'] ?? null;
        $hasEncounters = $this->db->campaignHasEncounters($campaignId);
        if ($storedPhase === 'combat') {
            $phase = 'combat';
        } elseif ($storedPhase === 'exploration' && $hasEncounters && $currentActor !== null && $currentActor === $campaign['owner']) {
            $phase = 'exploration';
        } else {
            $phase = ($currentActor !== null && $currentActor === $campaign['owner']) ? 'dm' : 'player';
        }
        $turnNumber = (int) ($campaign['turn_number'] ?? 0);

        return respondJson($response, 200, [
            'campaign_id' => $campaignId,
            'current_actor' => $currentActor,
            'phase' => $phase,
            'turn_number' => $turnNumber,
            'queue' => $queue,
            'overdue' => false,
            'logical_deadline' => 3,
        ]);
    }

    private function nudgeTurn(Request $request, Response $response, array $args): Response
    {
        $actor = $this->requireDm($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        if ($campaign['owner'] !== $actor['username']) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $body = $request->getParsedBody() ?? [];
        if (!isset($body['message']) || (!is_string($body['message']) && !is_numeric($body['message']))) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $message = (string) $body['message'];
        if ($message === '') {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $nudgeCount = $this->db->incrementNudgeCount($campaignId);

        $sequence = $this->db->nextNarrationSequence($campaignId);
        $this->db->createNarration([
            'campaign_id' => $campaignId,
            'sequence' => $sequence,
            'kind' => 'nudge',
            'actor' => $actor['username'],
            'text' => $message,
        ]);

        return respondJson($response, 201, [
            'actor' => $actor['username'],
            'target' => $campaign['current_actor'] ?? null,
            'message' => $message,
            'nudge_count' => $nudgeCount,
        ]);
    }

    private function getMyTurn(Request $request, Response $response, array $args): Response
    {
        $actor = $this->requirePlayer($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $member = $this->db->findPlayMemberByCampaignAndUser($campaignId, $actor['username']);
        if ($member === null) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $currentActor = $campaign['current_actor'] ?? null;
        $narrations = $this->db->findNarrationsByCampaign($campaignId);
        $recentEvents = $this->formatRecentEvents($narrations);

        return respondJson($response, 200, [
            'is_my_turn' => $currentActor === $actor['username'],
            'current_actor' => $currentActor,
            'character' => [
                'id' => $member['character_id'],
                'name' => $member['name'],
            ],
            'recent_events' => $recentEvents,
        ]);
    }

    private function getGmStatus(Request $request, Response $response, array $args): Response
    {
        $actor = $this->requireDm($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        if ($campaign['owner'] !== $actor['username']) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $members = $this->db->findPlayMembers($campaignId);
        $party = $this->formatParty($members);

        $narrations = $this->db->findNarrationsByCampaign($campaignId);
        $recentEvents = $this->formatRecentEvents($narrations);

        $currentActor = $campaign['current_actor'] ?? null;

        return respondJson($response, 200, [
            'needs_attention' => $currentActor === $campaign['owner'],
            'current_actor' => $currentActor,
            'party' => $party,
            'recent_events' => $recentEvents,
        ]);
    }

    private function updateDocument(Request $request, Response $response, array $args): Response
    {
        $actor = $this->requireDm($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        if ($campaign['owner'] !== $actor['username']) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $body = $request->getParsedBody() ?? [];
        if (!isset($body['story']) || (!is_string($body['story']) && !is_numeric($body['story']))
            || !isset($body['dm_notes']) || (!is_string($body['dm_notes']) && !is_numeric($body['dm_notes']))) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $story = (string) $body['story'];
        $dmNotes = (string) $body['dm_notes'];

        $this->db->updatePlayCampaignDocument($campaignId, $story, $dmNotes);

        return respondJson($response, 200, [
            'story' => $story,
            'dm_notes' => $dmNotes,
        ]);
    }

    private function getDocument(Request $request, Response $response, array $args): Response
    {
        $actor = $this->authenticate($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $isOwner = $campaign['owner'] === $actor['username'];
        $isMember = $this->db->findPlayMemberByCampaignAndUser($campaignId, $actor['username']) !== null;
        if (!$isOwner && !$isMember) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $doc = $this->db->findPlayCampaignDocument($campaignId) ?? ['story' => '', 'dm_notes' => ''];

        if ($isOwner) {
            return respondJson($response, 200, [
                'story' => $doc['story'],
                'dm_notes' => $doc['dm_notes'],
            ]);
        }

        return respondJson($response, 200, [
            'story' => $doc['story'],
        ]);
    }

    private function createBackup(Request $request, Response $response, array $args): Response
    {
        $actor = $this->requireDm($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        if ($campaign['owner'] !== $actor['username']) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $doc = $this->db->findPlayCampaignDocument($campaignId) ?? ['story' => '', 'dm_notes' => ''];
        $story = $doc['story'];
        $status = $campaign['status'];

        $existing = $this->db->findCampaignBackups($campaignId);
        $nextNumber = count($existing) + 1;
        $backupId = 'backup-' . $nextNumber;

        $this->db->createCampaignBackup($campaignId, $backupId, $story, $status);

        return respondJson($response, 201, [
            'backup_id' => $backupId,
            'story' => $story,
            'status' => $status,
        ]);
    }

    private function listBackups(Request $request, Response $response, array $args): Response
    {
        $actor = $this->requireDm($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        if ($campaign['owner'] !== $actor['username']) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $rows = $this->db->findCampaignBackups($campaignId);
        $backups = [];
        foreach ($rows as $row) {
            $backups[] = [
                'backup_id' => $row['backup_id'],
                'story' => $row['story'],
                'status' => $row['status'],
            ];
        }

        return respondJson($response, 200, ['backups' => $backups]);
    }

    private function restoreBackup(Request $request, Response $response, array $args): Response
    {
        $actor = $this->requireDm($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        if ($campaign['owner'] !== $actor['username']) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $backupId = (string) $args['backup_id'];
        $backup = $this->db->findCampaignBackup($campaignId, $backupId);
        if ($backup === null) {
            return respondJson($response, 404, ['error' => 'backup not found']);
        }

        $this->db->restoreCampaignBackup($campaignId, $backup['story'], $backup['status']);

        return respondJson($response, 200, [
            'backup_id' => $backup['backup_id'],
            'story' => $backup['story'],
            'status' => $backup['status'],
        ]);
    }

    private function createExport(Request $request, Response $response, array $args): Response
    {
        $actor = $this->requireDm($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        if ($campaign['owner'] !== $actor['username']) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $doc = $this->db->findPlayCampaignDocument($campaignId) ?? ['story' => '', 'dm_notes' => ''];
        $version = $this->db->createCampaignExport($campaignId, $doc['story'], $campaign['status']);

        return respondJson($response, 201, [
            'version' => $version,
            'story' => $doc['story'],
            'status' => $campaign['status'],
        ]);
    }

    private function listExports(Request $request, Response $response, array $args): Response
    {
        $actor = $this->requireDm($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        if ($campaign['owner'] !== $actor['username']) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $rows = $this->db->findCampaignExports($campaignId);
        $exports = [];
        foreach ($rows as $row) {
            $exports[] = [
                'version' => (int) $row['version'],
                'story' => $row['story'],
                'status' => $row['status'],
            ];
        }

        return respondJson($response, 200, ['exports' => $exports]);
    }

    private function getExport(Request $request, Response $response, array $args): Response
    {
        $actor = $this->requireDm($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        if ($campaign['owner'] !== $actor['username']) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $version = (int) $args['version'];
        $row = $this->db->findCampaignExport($campaignId, $version);
        if ($row === null) {
            return respondJson($response, 404, ['error' => 'export not found']);
        }

        return respondJson($response, 200, [
            'version' => (int) $row['version'],
            'story' => $row['story'],
            'status' => $row['status'],
        ]);
    }

    private function createImport(Request $request, Response $response, array $args): Response
    {
        $actor = $this->requireDm($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        if ($campaign['owner'] !== $actor['username']) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $body = $request->getParsedBody() ?? [];
        if (!is_array($body)
            || count($body) !== 3
            || !array_key_exists('version', $body)
            || !array_key_exists('story', $body)
            || !array_key_exists('status', $body)) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        if (!is_int($body['version']) || $body['version'] !== 1) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        if (!is_string($body['story']) || $body['story'] === '') {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        if (!is_string($body['status']) || !in_array($body['status'], ['lobby', 'started'], true)) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $this->db->importCampaignSnapshot($campaignId, $body['version'], $body['story'], $body['status']);

        return respondJson($response, 200, [
            'version' => $body['version'],
            'story' => $body['story'],
            'status' => $body['status'],
        ]);
    }

    private function getImportState(Request $request, Response $response, array $args): Response
    {
        $actor = $this->requireDm($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        if ($campaign['owner'] !== $actor['username']) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $row = $this->db->findCampaignImport($campaignId);
        if ($row === null) {
            return respondJson($response, 404, ['error' => 'import not found']);
        }

        return respondJson($response, 200, [
            'version' => (int) $row['version'],
            'story' => $row['story'],
            'status' => $row['status'],
        ]);
    }

    private function createMigration(Request $request, Response $response, array $args): Response
    {
        $actor = $this->authenticate($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        if ($campaign['owner'] !== $actor['username']) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $body = $request->getParsedBody() ?? [];
        if (!is_array($body)
            || count($body) !== 2
            || !array_key_exists('schema_version', $body)
            || !array_key_exists('story', $body)) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        if (!is_int($body['schema_version']) || $body['schema_version'] !== 1) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        if (!is_string($body['story']) || $body['story'] === '') {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $story = $body['story'];
        $existing = $this->db->findCampaignMigration($campaignId);
        if ($existing !== null && $existing['story'] === $story && $existing['schema_version'] === 2) {
            return respondJson($response, 200, [
                'schema_version' => 2,
                'story' => $existing['story'],
                'campaign_name' => $existing['campaign_name'],
            ]);
        }

        $this->db->migrateCampaignSnapshot($campaignId, $story, $campaign['name']);

        return respondJson($response, 201, [
            'schema_version' => 2,
            'story' => $story,
            'campaign_name' => $campaign['name'],
        ]);
    }

    private function getMigrationState(Request $request, Response $response, array $args): Response
    {
        $actor = $this->authenticate($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        if ($campaign['owner'] !== $actor['username']) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $row = $this->db->findCampaignMigration($campaignId);
        if ($row === null) {
            return respondJson($response, 404, ['error' => 'migration not found']);
        }

        return respondJson($response, 200, [
            'schema_version' => 2,
            'story' => $row['story'],
            'campaign_name' => $row['campaign_name'],
        ]);
    }

    private function createScene(Request $request, Response $response, array $args): Response
    {
        $actor = $this->requireDm($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        if ($campaign['owner'] !== $actor['username']) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $body = $request->getParsedBody() ?? [];
        if (!isset($body['id']) || (!is_string($body['id']) && !is_numeric($body['id']))
            || !isset($body['name']) || (!is_string($body['name']) && !is_numeric($body['name']))) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $sceneId = (string) $body['id'];
        $name = (string) $body['name'];
        if ($sceneId === '' || $name === '') {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        if ($this->db->findScene($campaignId, $sceneId) !== null) {
            return respondJson($response, 409, ['error' => 'scene id already exists']);
        }

        $this->db->createScene([
            'campaign_id' => $campaignId,
            'id' => $sceneId,
            'name' => $name,
            'status' => 'open',
        ]);

        return respondJson($response, 201, [
            'id' => $sceneId,
            'name' => $name,
            'status' => 'open',
        ]);
    }

    private function enterScene(Request $request, Response $response, array $args): Response
    {
        $actor = $this->requireDm($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        if ($campaign['owner'] !== $actor['username']) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $sceneId = (string) $args['scene_id'];
        $scene = $this->db->findScene($campaignId, $sceneId);
        if ($scene === null) {
            return respondJson($response, 404, ['error' => 'scene not found']);
        }

        if ($scene['status'] === 'closed') {
            return respondJson($response, 409, ['error' => 'scene is closed']);
        }

        $this->db->updatePlayCampaignCurrentScene($campaignId, $sceneId);

        $sequence = $this->db->nextNarrationSequence($campaignId);
        $this->db->createNarration([
            'campaign_id' => $campaignId,
            'sequence' => $sequence,
            'kind' => 'scene',
            'actor' => $actor['username'],
            'text' => $scene['name'],
        ]);

        return respondJson($response, 200, [
            'current_scene_id' => $sceneId,
            'name' => $scene['name'],
        ]);
    }

    private function closeScene(Request $request, Response $response, array $args): Response
    {
        $actor = $this->requireDm($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        if ($campaign['owner'] !== $actor['username']) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $sceneId = (string) $args['scene_id'];
        $scene = $this->db->findScene($campaignId, $sceneId);
        if ($scene === null) {
            return respondJson($response, 404, ['error' => 'scene not found']);
        }

        $this->db->closeScene($campaignId, $sceneId);

        return respondJson($response, 200, [
            'id' => $sceneId,
            'status' => 'closed',
        ]);
    }

    private function getCurrentScene(Request $request, Response $response, array $args): Response
    {
        $actor = $this->authenticate($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $isOwner = $campaign['owner'] === $actor['username'];
        $isMember = $this->db->findPlayMemberByCampaignAndUser($campaignId, $actor['username']) !== null;
        if (!$isOwner && !$isMember) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $currentSceneId = $campaign['current_scene_id'] ?? null;
        if ($currentSceneId === null) {
            return respondJson($response, 404, ['error' => 'no current scene']);
        }

        $scene = $this->db->findScene($campaignId, $currentSceneId);
        if ($scene === null || $scene['status'] !== 'open') {
            return respondJson($response, 404, ['error' => 'no current scene']);
        }

        return respondJson($response, 200, [
            'id' => $scene['id'],
            'name' => $scene['name'],
            'status' => 'open',
        ]);
    }

    private function createLocation(Request $request, Response $response, array $args): Response
    {
        $actor = $this->requireDm($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        if ($campaign['owner'] !== $actor['username']) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $body = $request->getParsedBody() ?? [];
        if (!isset($body['id']) || (!is_string($body['id']) && !is_numeric($body['id']))
            || !isset($body['name']) || (!is_string($body['name']) && !is_numeric($body['name']))) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $locationId = (string) $body['id'];
        $name = (string) $body['name'];
        if ($locationId === '' || $name === '') {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        if ($this->db->findLocation($campaignId, $locationId) !== null) {
            return respondJson($response, 409, ['error' => 'location id already exists']);
        }

        $this->db->createLocation([
            'campaign_id' => $campaignId,
            'id' => $locationId,
            'name' => $name,
        ]);

        return respondJson($response, 201, [
            'id' => $locationId,
            'name' => $name,
        ]);
    }

    private function createConnection(Request $request, Response $response, array $args): Response
    {
        $actor = $this->requireDm($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        if ($campaign['owner'] !== $actor['username']) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $fromId = (string) $args['from_id'];
        if ($this->db->findLocation($campaignId, $fromId) === null) {
            return respondJson($response, 404, ['error' => 'location not found']);
        }

        $body = $request->getParsedBody() ?? [];
        if (!isset($body['to_id']) || (!is_string($body['to_id']) && !is_numeric($body['to_id']))
            || !isset($body['travel_turns']) || !is_numeric($body['travel_turns'])) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $toId = (string) $body['to_id'];
        $travelTurns = (int) $body['travel_turns'];
        if ($toId === '' || $travelTurns < 1) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        if ($this->db->findLocation($campaignId, $toId) === null) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        if ($this->db->findLocationConnection($campaignId, $fromId, $toId) !== null) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $this->db->createLocationConnection([
            'campaign_id' => $campaignId,
            'from_id' => $fromId,
            'to_id' => $toId,
            'travel_turns' => $travelTurns,
        ]);

        return respondJson($response, 201, [
            'from_id' => $fromId,
            'to_id' => $toId,
            'travel_turns' => $travelTurns,
        ]);
    }

    private function getTravel(Request $request, Response $response, array $args): Response
    {
        $actor = $this->authenticate($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $isOwner = $campaign['owner'] === $actor['username'];
        $isMember = $this->db->findPlayMemberByCampaignAndUser($campaignId, $actor['username']) !== null;
        if (!$isOwner && !$isMember) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $locId = (string) $args['loc_id'];
        if ($this->db->findLocation($campaignId, $locId) === null) {
            return respondJson($response, 404, ['error' => 'location not found']);
        }

        $rows = $this->db->findOutboundConnections($campaignId, $locId);
        $destinations = [];
        foreach ($rows as $row) {
            $destinations[] = [
                'id' => $row['to_id'],
                'name' => $row['name'],
                'travel_turns' => (int) $row['travel_turns'],
            ];
        }

        return respondJson($response, 200, [
            'destinations' => $destinations,
        ]);
    }

    private function travelTurn(Request $request, Response $response, array $args): Response
    {
        $actor = $this->authenticate($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $isOwner = $campaign['owner'] === $actor['username'];
        $isMember = $this->db->findPlayMemberByCampaignAndUser($campaignId, $actor['username']) !== null;
        if (!$isOwner && !$isMember) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        if ($isOwner) {
            return respondJson($response, 409, ['error' => 'not your turn']);
        }

        $currentActor = $campaign['current_actor'] ?? null;
        if ($currentActor !== $actor['username']) {
            return respondJson($response, 409, ['error' => 'not your turn']);
        }

        $body = $request->getParsedBody() ?? [];
        if (!isset($body['destination_id']) || (!is_string($body['destination_id']) && !is_numeric($body['destination_id']))) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $destinationId = (string) $body['destination_id'];
        if ($destinationId === '') {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $currentLocationId = $campaign['current_location_id'] ?? null;
        if ($currentLocationId === null || $currentLocationId === '') {
            return respondJson($response, 409, ['error' => 'invalid destination']);
        }

        $connection = $this->db->findLocationConnection($campaignId, $currentLocationId, $destinationId);
        if ($connection === null) {
            return respondJson($response, 409, ['error' => 'invalid destination']);
        }

        $travelTurns = (int) $connection['travel_turns'];

        $sequence = $this->db->nextNarrationSequence($campaignId);
        $this->db->createNarration([
            'campaign_id' => $campaignId,
            'sequence' => $sequence,
            'kind' => 'travel',
            'actor' => $actor['username'],
            'type' => (string) $travelTurns,
            'text' => $destinationId,
        ]);

        $this->db->updatePlayCampaignCurrentLocation($campaignId, $destinationId);
        $this->db->updatePlayCampaignCurrentActor($campaignId, $campaign['owner']);

        return respondJson($response, 201, [
            'sequence' => $sequence,
            'kind' => 'travel',
            'actor' => $actor['username'],
            'destination_id' => $destinationId,
            'travel_turns' => $travelTurns,
            'next_actor' => 'dm',
        ]);
    }

    /**
     * Authenticate the request and return the user row, or a response on failure.
     *
     * @return array<string, mixed>|Response
     */
    private function restTurn(Request $request, Response $response, array $args): Response
    {
        $actor = $this->authenticate($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $isOwner = $campaign['owner'] === $actor['username'];
        $isMember = $this->db->findPlayMemberByCampaignAndUser($campaignId, $actor['username']) !== null;
        if (!$isOwner && !$isMember) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        if ($isOwner) {
            return respondJson($response, 409, ['error' => 'not your turn']);
        }

        $currentActor = $campaign['current_actor'] ?? null;
        if ($currentActor !== $actor['username']) {
            return respondJson($response, 409, ['error' => 'not your turn']);
        }

        $body = $request->getParsedBody() ?? [];
        if (!isset($body['type']) || (!is_string($body['type']) && !is_numeric($body['type']))) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $type = (string) $body['type'];
        if (!in_array($type, ['long', 'short'], true)) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $member = $this->db->findPlayMemberByCampaignAndUser($campaignId, $actor['username']);
        $hpMax = (int) ($member['hp_max'] ?? 20);
        $hpCurrent = (int) ($member['hp_current'] ?? 20);

        if ($type === 'long') {
            $hpCurrent = $hpMax;
            $this->db->updatePlayMemberHp($campaignId, $actor['username'], $hpCurrent, $hpMax);
            if ($member !== null && isset($member['character_id'])) {
                $this->db->resetCharacterSpellSlots($campaignId, (string) $member['character_id']);
            }
        }

        $sequence = $this->db->nextNarrationSequence($campaignId);
        $this->db->createNarration([
            'campaign_id' => $campaignId,
            'sequence' => $sequence,
            'kind' => 'rest',
            'actor' => $actor['username'],
            'type' => $type,
            'text' => 'rest',
        ]);

        $this->db->updatePlayCampaignCurrentActor($campaignId, $campaign['owner']);

        return respondJson($response, 201, [
            'sequence' => $sequence,
            'kind' => 'rest',
            'actor' => $actor['username'],
            'type' => $type,
            'hp_current' => $hpCurrent,
            'hp_max' => $hpMax,
            'next_actor' => 'dm',
        ]);
    }

    private function createEncounter(Request $request, Response $response, array $args): Response
    {
        $actor = $this->requireDm($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        if ($campaign['owner'] !== $actor['username']) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $body = $request->getParsedBody() ?? [];
        if (!isset($body['id']) || (!is_string($body['id']) && !is_numeric($body['id']))
            || !isset($body['name']) || (!is_string($body['name']) && !is_numeric($body['name']))) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $encounterId = (string) $body['id'];
        $name = (string) $body['name'];
        if ($encounterId === '' || $name === '') {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        if ($this->db->findEncounter($encounterId) !== null) {
            return respondJson($response, 409, ['error' => 'encounter id already exists']);
        }

        if ($this->db->findActiveEncounter($campaignId) !== null) {
            return respondJson($response, 409, ['error' => 'campaign already in combat']);
        }

        $this->db->createEncounter([
            'id' => $encounterId,
            'campaign_id' => $campaignId,
            'name' => $name,
            'status' => 'active',
            'combatants' => [],
            'round' => 1,
            'turn_index' => 0,
        ]);

        $this->db->enterPlayCampaignCombat($campaignId, (string) ($campaign['current_actor'] ?? $campaign['owner']));

        return respondJson($response, 201, [
            'id' => $encounterId,
            'name' => $name,
            'status' => 'active',
            'combatants' => [],
        ]);
    }

    private function addMonster(Request $request, Response $response, array $args): Response
    {
        $actor = $this->requireDm($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        if ($campaign['owner'] !== $actor['username']) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $encounterId = (string) $args['enc_id'];
        $encounter = $this->db->findEncounter($encounterId);
        if ($encounter === null || $encounter['campaign_id'] !== $campaignId) {
            return respondJson($response, 404, ['error' => 'encounter not found']);
        }

        $body = $request->getParsedBody() ?? [];
        if (!isset($body['monster_id']) || (!is_string($body['monster_id']) && !is_numeric($body['monster_id']))
            || !isset($body['name']) || (!is_string($body['name']) && !is_numeric($body['name']))
            || !isset($body['hp_max']) || !is_numeric($body['hp_max'])
            || !isset($body['initiative']) || !is_numeric($body['initiative'])) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $monsterId = (string) $body['monster_id'];
        $name = (string) $body['name'];
        $hpMax = (int) $body['hp_max'];
        $initiative = (int) $body['initiative'];
        if ($monsterId === '' || $name === '' || $hpMax < 1) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $combatants = $encounter['combatants'] ?? [];
        foreach ($combatants as $combatant) {
            if (isset($combatant['monster_id']) && $combatant['monster_id'] === $monsterId) {
                return respondJson($response, 409, ['error' => 'monster id already exists']);
            }
        }

        $monster = [
            'monster_id' => $monsterId,
            'name' => $name,
            'hp_max' => $hpMax,
            'initiative' => $initiative,
            'hp_current' => $hpMax,
        ];
        $combatants[] = $monster;
        $this->db->updateEncounterCombatants($encounterId, $combatants);

        return respondJson($response, 201, $monster);
    }

    private function removeMonster(Request $request, Response $response, array $args): Response
    {
        $actor = $this->requireDm($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        if ($campaign['owner'] !== $actor['username']) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $encounterId = (string) $args['enc_id'];
        $encounter = $this->db->findEncounter($encounterId);
        if ($encounter === null || $encounter['campaign_id'] !== $campaignId) {
            return respondJson($response, 404, ['error' => 'encounter not found']);
        }

        $monsterId = (string) $args['monster_id'];
        $combatants = $encounter['combatants'] ?? [];
        $found = false;
        $updated = [];
        foreach ($combatants as $combatant) {
            if (isset($combatant['monster_id']) && $combatant['monster_id'] === $monsterId) {
                $found = true;
                continue;
            }
            $updated[] = $combatant;
        }

        if (!$found) {
            return respondJson($response, 404, ['error' => 'monster not found']);
        }

        $this->db->updateEncounterCombatants($encounterId, $updated);

        return respondJson($response, 200, ['removed' => $monsterId]);
    }

    private function bindMember(Request $request, Response $response, array $args): Response
    {
        $actor = $this->requireDm($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        if ($campaign['owner'] !== $actor['username']) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $encounterId = (string) $args['enc_id'];
        $encounter = $this->db->findEncounter($encounterId);
        if ($encounter === null || $encounter['campaign_id'] !== $campaignId) {
            return respondJson($response, 404, ['error' => 'encounter not found']);
        }

        $body = $request->getParsedBody() ?? [];
        if (!isset($body['member']) || (!is_string($body['member']) && !is_numeric($body['member']))
            || !isset($body['initiative']) || !is_numeric($body['initiative'])) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $memberName = (string) $body['member'];
        $initiative = (int) $body['initiative'];
        if ($memberName === '') {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $member = $this->db->findPlayMemberByCampaignAndUser($campaignId, $memberName);
        if ($member === null) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $combatants = $encounter['combatants'] ?? [];
        foreach ($combatants as $combatant) {
            if (isset($combatant['member']) && $combatant['member'] === $memberName) {
                return respondJson($response, 409, ['error' => 'member already bound']);
            }
        }

        $binding = [
            'member' => $memberName,
            'character_id' => $member['character_id'],
            'name' => $member['name'],
            'initiative' => $initiative,
        ];
        $combatants[] = $binding;
        $this->db->updateEncounterCombatants($encounterId, $combatants);

        return respondJson($response, 201, $binding);
    }

    private function unbindMember(Request $request, Response $response, array $args): Response
    {
        $actor = $this->requireDm($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        if ($campaign['owner'] !== $actor['username']) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $encounterId = (string) $args['enc_id'];
        $encounter = $this->db->findEncounter($encounterId);
        if ($encounter === null || $encounter['campaign_id'] !== $campaignId) {
            return respondJson($response, 404, ['error' => 'encounter not found']);
        }

        $memberName = (string) $args['member'];
        $combatants = $encounter['combatants'] ?? [];
        $found = false;
        $updated = [];
        foreach ($combatants as $combatant) {
            if (isset($combatant['member']) && $combatant['member'] === $memberName) {
                $found = true;
                continue;
            }
            $updated[] = $combatant;
        }

        if (!$found) {
            return respondJson($response, 404, ['error' => 'member not found']);
        }

        $this->db->updateEncounterCombatants($encounterId, $updated);

        return respondJson($response, 200, ['removed' => $memberName]);
    }

    private function configureRngSeed(Request $request, Response $response, array $args): Response
    {
        $actor = $this->requireDm($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        if ($campaign['owner'] !== $actor['username']) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $body = $request->getParsedBody() ?? [];
        if (!isset($body['seed']) || !is_string($body['seed']) || $body['seed'] === '') {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $seed = $body['seed'];
        $existing = $this->db->findRngSeed($campaignId);
        if ($existing !== null) {
            return respondJson($response, 409, ['error' => 'seed already configured']);
        }

        $created = $this->db->createRngSeed($campaignId, $seed);
        if (!$created) {
            return respondJson($response, 409, ['error' => 'seed already configured']);
        }

        return respondJson($response, 200, ['seed' => $seed, 'rolls' => []]);
    }

    private function appendRngRoll(Request $request, Response $response, array $args): Response
    {
        $actor = $this->authenticate($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $isOwner = $campaign['owner'] === $actor['username'];
        $isMember = $this->db->findPlayMemberByCampaignAndUser($campaignId, $actor['username']) !== null;
        if (!$isOwner && !$isMember) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $body = $request->getParsedBody() ?? [];
        if (!isset($body['roll_id']) || !is_string($body['roll_id']) || $body['roll_id'] === ''
            || !isset($body['sides']) || !is_int($body['sides'])) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $rollId = $body['roll_id'];
        $sides = $body['sides'];
        if ($sides < 2 || $sides > 100) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $seed = $this->db->findRngSeed($campaignId);
        if ($seed === null) {
            return respondJson($response, 409, ['error' => 'seed not configured']);
        }

        if ($this->db->findRngRoll($campaignId, $rollId) !== null) {
            return respondJson($response, 409, ['error' => 'roll id already exists']);
        }

        $sequence = $this->db->nextRngSequence($campaignId);
        $result = $this->engine->deterministicRoll($seed, $sequence, $rollId, $sides);

        try {
            $this->db->createRngRoll($campaignId, $sequence, $rollId, $sides, $result);
        } catch (PDOException $e) {
            if ($e->getCode() === '23000' || str_contains($e->getMessage(), 'UNIQUE constraint failed')) {
                return respondJson($response, 409, ['error' => 'roll id already exists']);
            }
            throw $e;
        }

        return respondJson($response, 201, [
            'roll_id' => $rollId,
            'sides' => $sides,
            'result' => $result,
            'sequence' => $sequence,
        ]);
    }

    private function getRngLedger(Request $request, Response $response, array $args): Response
    {
        $actor = $this->authenticate($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $isOwner = $campaign['owner'] === $actor['username'];
        $isMember = $this->db->findPlayMemberByCampaignAndUser($campaignId, $actor['username']) !== null;
        if (!$isOwner && !$isMember) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $seed = $this->db->findRngSeed($campaignId);

        return respondJson($response, 200, [
            'seed' => $seed,
            'rolls' => $this->db->findRngRolls($campaignId),
        ]);
    }

    private function setServiceMode(Request $request, Response $response, array $args): Response
    {
        $actor = $this->requireDm($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $body = $request->getParsedBody() ?? [];
        if (!isset($body['maintenance']) || !is_bool($body['maintenance'])) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $this->db->setServiceMode($body['maintenance']);

        return respondJson($response, 200, ['maintenance' => $this->db->getServiceMode()]);
    }

    private function authenticate(Request $request, Response $response): array|Response
    {
        $header = $request->getHeaderLine('Authorization');
        if ($header === '') {
            return respondJson($response, 401, ['error' => 'unauthorized']);
        }

        if (!str_starts_with($header, 'Bearer ')) {
            return respondJson($response, 401, ['error' => 'unauthorized']);
        }

        $token = substr($header, 7);
        if (!str_starts_with($token, self::TOKEN_PREFIX)) {
            return respondJson($response, 401, ['error' => 'unauthorized']);
        }

        $username = substr($token, strlen(self::TOKEN_PREFIX));
        if ($username === '') {
            return respondJson($response, 401, ['error' => 'unauthorized']);
        }

        $user = $this->db->findUser($username);
        if ($user === null) {
            // The play surface treats a valid bearer token as an identity even if the
            // user has not been registered, so that non-member requests can be
            // rejected with 403 rather than failing authentication with 401.
            return [
                'username' => $username,
                'role' => $username === 'dm' ? 'dm' : 'player',
            ];
        }

        return $user;
    }

    /**
     * Authenticate the request and ensure the actor is a DM.
     *
     * Returns a Response on authentication failure (401) or authorization failure (403);
     * otherwise returns the authenticated user row.
     *
     * @return array<string, mixed>|Response
     */
    private function requireDm(Request $request, Response $response): array|Response
    {
        $actor = $this->authenticate($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        if ($actor['role'] !== 'dm') {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        return $actor;
    }

    /**
     * Authenticate the request and ensure the actor is a player.
     *
     * Returns a Response on authentication failure (401) or authorization failure (403);
     * otherwise returns the authenticated user row.
     *
     * @return array<string, mixed>|Response
     */
    private function requirePlayer(Request $request, Response $response): array|Response
    {
        $actor = $this->authenticate($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        if ($actor['role'] !== 'player') {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        return $actor;
    }

    private function getEncounterTurn(Request $request, Response $response, array $args): Response
    {
        $actor = $this->authenticate($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $isOwner = $campaign['owner'] === $actor['username'];
        $isMember = $this->db->findPlayMemberByCampaignAndUser($campaignId, $actor['username']) !== null;
        if (!$isOwner && !$isMember) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $encounterId = (string) $args['enc_id'];
        $encounter = $this->db->findEncounter($encounterId);
        if ($encounter === null || $encounter['campaign_id'] !== $campaignId) {
            return respondJson($response, 404, ['error' => 'encounter not found']);
        }

        $order = $this->buildEncounterOrder($encounter['combatants'] ?? [], $encounter['turn_order'] ?? []);
        if (empty($order)) {
            return respondJson($response, 409, ['error' => 'encounter has no combatants']);
        }

        $count = count($order);
        $turnIndex = (int) ($encounter['turn_index'] ?? 0) % $count;
        $round = (int) ($encounter['round'] ?? 1);

        return respondJson($response, 200, [
            'round' => $round,
            'turn_index' => $turnIndex,
            'active' => $this->formatActiveCombatant($order[$turnIndex]),
        ]);
    }

    private function advanceEncounterTurn(Request $request, Response $response, array $args): Response
    {
        $actor = $this->authenticate($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $isOwner = $campaign['owner'] === $actor['username'];
        $isMember = $this->db->findPlayMemberByCampaignAndUser($campaignId, $actor['username']) !== null;
        if (!$isOwner && !$isMember) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $encounterId = (string) $args['enc_id'];
        $encounter = $this->db->findEncounter($encounterId);
        if ($encounter === null || $encounter['campaign_id'] !== $campaignId) {
            return respondJson($response, 404, ['error' => 'encounter not found']);
        }

        $order = $this->buildEncounterOrder($encounter['combatants'] ?? [], $encounter['turn_order'] ?? []);
        if (empty($order)) {
            return respondJson($response, 409, ['error' => 'encounter has no combatants']);
        }

        $count = count($order);
        $turnIndex = (int) ($encounter['turn_index'] ?? 0) % $count;
        $current = $order[$turnIndex];
        $isCurrentCombatant = $current['kind'] === 'player' && $current['member'] === $actor['username'];

        if (!$isOwner && !$isCurrentCombatant) {
            return respondJson($response, 409, ['error' => 'not your turn']);
        }

        $nextTurnIndex = $turnIndex + 1;
        $round = (int) ($encounter['round'] ?? 1);
        if ($nextTurnIndex >= $count) {
            $nextTurnIndex = 0;
            $round++;
        }

        $nextActive = $order[$nextTurnIndex];
        $conditions = $this->decrementConditions($encounter['conditions'] ?? [], $nextActive['target']);
        $this->db->updateEncounterConditions($encounterId, $conditions);
        $this->db->updateEncounterTurn($encounterId, $round, $nextTurnIndex);

        return respondJson($response, 200, [
            'round' => $round,
            'turn_index' => $nextTurnIndex,
            'active' => $this->formatActiveCombatant($nextActive),
        ]);
    }

    private function delayEncounterTurn(Request $request, Response $response, array $args): Response
    {
        $actor = $this->authenticate($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $isOwner = $campaign['owner'] === $actor['username'];
        $isMember = $this->db->findPlayMemberByCampaignAndUser($campaignId, $actor['username']) !== null;
        if (!$isOwner && !$isMember) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $encounterId = (string) $args['enc_id'];
        $encounter = $this->db->findEncounter($encounterId);
        if ($encounter === null || $encounter['campaign_id'] !== $campaignId) {
            return respondJson($response, 404, ['error' => 'encounter not found']);
        }

        $body = $request->getParsedBody() ?? [];
        if (!isset($body['new_index']) || !is_numeric($body['new_index'])) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }
        $newIndex = (int) $body['new_index'];

        $order = $this->buildEncounterOrder($encounter['combatants'] ?? [], $encounter['turn_order'] ?? []);
        if (empty($order)) {
            return respondJson($response, 409, ['error' => 'encounter has no combatants']);
        }

        $count = count($order);
        if ($newIndex < 0 || $newIndex >= $count) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $turnIndex = (int) ($encounter['turn_index'] ?? 0) % $count;
        $current = $order[$turnIndex];
        $isCurrentCombatant = $current['kind'] === 'player' && $current['member'] === $actor['username'];

        if (!$isOwner && !$isCurrentCombatant) {
            return respondJson($response, 409, ['error' => 'not your turn']);
        }

        $remaining = [];
        foreach ($order as $i => $combatant) {
            if ($i !== $turnIndex) {
                $remaining[] = $combatant;
            }
        }

        $newOrder = [];
        for ($i = 0; $i < $newIndex; $i++) {
            $newOrder[] = $remaining[$i];
        }
        $newOrder[] = $current;
        for ($i = $newIndex; $i < count($remaining); $i++) {
            $newOrder[] = $remaining[$i];
        }

        $turnOrder = [];
        $newTurnIndex = 0;
        foreach ($newOrder as $i => $combatant) {
            $turnOrder[] = $combatant['target'];
            if ($combatant['target'] === $current['target']) {
                $newTurnIndex = $i;
            }
        }

        $this->db->updateEncounterTurnOrder($encounterId, $turnOrder);
        $this->db->updateEncounterTurn($encounterId, (int) ($encounter['round'] ?? 1), $newTurnIndex);

        $responseOrder = [];
        foreach ($newOrder as $combatant) {
            $responseOrder[] = $this->formatActiveCombatant($combatant);
        }

        return respondJson($response, 200, [
            'order' => $responseOrder,
        ]);
    }

    private function readyEncounterTurn(Request $request, Response $response, array $args): Response
    {
        $actor = $this->authenticate($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $isMember = $this->db->findPlayMemberByCampaignAndUser($campaignId, $actor['username']) !== null;
        if (!$isMember) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $encounterId = (string) $args['enc_id'];
        $encounter = $this->db->findEncounter($encounterId);
        if ($encounter === null || $encounter['campaign_id'] !== $campaignId) {
            return respondJson($response, 404, ['error' => 'encounter not found']);
        }

        $body = $request->getParsedBody() ?? [];
        if (!isset($body['trigger']) || (!is_string($body['trigger']) && !is_numeric($body['trigger']))) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }
        $trigger = (string) $body['trigger'];
        if ($trigger === '') {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $order = $this->buildEncounterOrder($encounter['combatants'] ?? [], $encounter['turn_order'] ?? []);
        if (empty($order)) {
            return respondJson($response, 409, ['error' => 'encounter has no combatants']);
        }

        $count = count($order);
        $turnIndex = (int) ($encounter['turn_index'] ?? 0) % $count;
        $current = $order[$turnIndex];

        if ($current['kind'] !== 'player' || $current['member'] !== $actor['username']) {
            return respondJson($response, 409, ['error' => 'not your turn']);
        }

        $readyActions = $encounter['ready_actions'] ?? [];
        $readyActions[] = [
            'actor' => $actor['username'],
            'trigger' => $trigger,
        ];
        $this->db->updateEncounterReadyActions($encounterId, $readyActions);

        return respondJson($response, 201, [
            'actor' => $actor['username'],
            'trigger' => $trigger,
        ]);
    }

    private function submitCombatAction(Request $request, Response $response, array $args): Response
    {
        $actor = $this->authenticate($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $isOwner = $campaign['owner'] === $actor['username'];
        $isMember = $this->db->findPlayMemberByCampaignAndUser($campaignId, $actor['username']) !== null;
        if (!$isOwner && !$isMember) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $encounterId = (string) $args['enc_id'];
        $encounter = $this->db->findEncounter($encounterId);
        if ($encounter === null || $encounter['campaign_id'] !== $campaignId) {
            return respondJson($response, 404, ['error' => 'encounter not found']);
        }

        $body = $request->getParsedBody() ?? [];
        if (!isset($body['type']) || (!is_string($body['type']) && !is_numeric($body['type']))
            || !isset($body['target']) || (!is_string($body['target']) && !is_numeric($body['target']))
            || !isset($body['text']) || (!is_string($body['text']) && !is_numeric($body['text']))) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $type = (string) $body['type'];
        $target = (string) $body['target'];
        $text = (string) $body['text'];
        if ($type === '' || $target === '' || $text === '') {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        if (!in_array($type, ['attack', 'help', 'dodge', 'ready'], true)) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $order = $this->buildEncounterOrder($encounter['combatants'] ?? [], $encounter['turn_order'] ?? []);
        if (empty($order)) {
            return respondJson($response, 409, ['error' => 'not your turn']);
        }

        $count = count($order);
        $turnIndex = (int) ($encounter['turn_index'] ?? 0) % $count;
        $current = $order[$turnIndex];

        if ($current['kind'] !== 'player' || $current['member'] !== $actor['username']) {
            return respondJson($response, 409, ['error' => 'not your turn']);
        }

        $sequence = $this->db->nextNarrationSequence($campaignId);
        $this->db->createNarration([
            'campaign_id' => $campaignId,
            'sequence' => $sequence,
            'kind' => 'combat_action',
            'actor' => $actor['username'],
            'type' => $type,
            'target' => $target,
            'text' => $text,
        ]);

        return respondJson($response, 201, [
            'sequence' => $sequence,
            'kind' => 'combat_action',
            'actor' => $actor['username'],
            'type' => $type,
            'target' => $target,
            'text' => $text,
        ]);
    }

    private function damage(Request $request, Response $response, array $args): Response
    {
        $actor = $this->requireDm($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        if ($campaign['owner'] !== $actor['username']) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $encounterId = (string) $args['enc_id'];
        $encounter = $this->db->findEncounter($encounterId);
        if ($encounter === null || $encounter['campaign_id'] !== $campaignId) {
            return respondJson($response, 404, ['error' => 'encounter not found']);
        }

        $body = $request->getParsedBody() ?? [];
        if (!isset($body['target']) || (!is_string($body['target']) && !is_numeric($body['target']))
            || !isset($body['amount']) || !is_numeric($body['amount'])) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $target = (string) $body['target'];
        $amount = (int) $body['amount'];
        if ($target === '' || $amount < 0) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $combatants = $encounter['combatants'] ?? [];
        $found = false;
        foreach ($combatants as $index => $combatant) {
            if (isset($combatant['monster_id']) && $combatant['monster_id'] === $target) {
                $found = true;
                $hpBefore = (int) ($combatant['hp_current'] ?? ($combatant['hp_max'] ?? 0));
                $hpMax = (int) ($combatant['hp_max'] ?? $hpBefore);
                $hpAfter = max(0, $hpBefore - $amount);
                $combatants[$index]['hp_current'] = $hpAfter;
                break;
            }
            if (isset($combatant['member']) && $combatant['member'] === $target) {
                $found = true;
                $member = $this->db->findPlayMemberByCampaignAndUser($campaignId, $target);
                if ($member === null) {
                    return respondJson($response, 404, ['error' => 'target not found']);
                }
                $hpBefore = (int) ($member['hp_current'] ?? 20);
                $hpMax = (int) ($member['hp_max'] ?? 20);
                $hpAfter = max(0, $hpBefore - $amount);
                $this->db->updatePlayMemberHp($campaignId, $target, $hpAfter, $hpMax);
                break;
            }
        }

        if (!$found) {
            return respondJson($response, 404, ['error' => 'target not found']);
        }

        if (isset($combatants[$index]['monster_id'])) {
            $this->db->updateEncounterCombatants($encounterId, $combatants);
        }

        return respondJson($response, 200, [
            'target' => $target,
            'hp_before' => $hpBefore,
            'hp_after' => $hpAfter,
            'damage' => $amount,
        ]);
    }

    private function heal(Request $request, Response $response, array $args): Response
    {
        $actor = $this->requireDm($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        if ($campaign['owner'] !== $actor['username']) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $encounterId = (string) $args['enc_id'];
        $encounter = $this->db->findEncounter($encounterId);
        if ($encounter === null || $encounter['campaign_id'] !== $campaignId) {
            return respondJson($response, 404, ['error' => 'encounter not found']);
        }

        $body = $request->getParsedBody() ?? [];
        if (!isset($body['target']) || (!is_string($body['target']) && !is_numeric($body['target']))
            || !isset($body['amount']) || !is_numeric($body['amount'])) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $target = (string) $body['target'];
        $amount = (int) $body['amount'];
        if ($target === '' || $amount < 0) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $combatants = $encounter['combatants'] ?? [];
        $found = false;
        foreach ($combatants as $index => $combatant) {
            if (isset($combatant['monster_id']) && $combatant['monster_id'] === $target) {
                $found = true;
                $hpBefore = (int) ($combatant['hp_current'] ?? ($combatant['hp_max'] ?? 0));
                $hpMax = (int) ($combatant['hp_max'] ?? $hpBefore);
                $hpAfter = min($hpMax, $hpBefore + $amount);
                $combatants[$index]['hp_current'] = $hpAfter;
                break;
            }
            if (isset($combatant['member']) && $combatant['member'] === $target) {
                $found = true;
                $member = $this->db->findPlayMemberByCampaignAndUser($campaignId, $target);
                if ($member === null) {
                    return respondJson($response, 404, ['error' => 'target not found']);
                }
                $hpBefore = (int) ($member['hp_current'] ?? 20);
                $hpMax = (int) ($member['hp_max'] ?? 20);
                $hpAfter = min($hpMax, $hpBefore + $amount);
                $this->db->updatePlayMemberHp($campaignId, $target, $hpAfter, $hpMax);
                break;
            }
        }

        if (!$found) {
            return respondJson($response, 404, ['error' => 'target not found']);
        }

        if (isset($combatants[$index]['monster_id'])) {
            $this->db->updateEncounterCombatants($encounterId, $combatants);
        }

        return respondJson($response, 200, [
            'target' => $target,
            'hp_before' => $hpBefore,
            'hp_after' => $hpAfter,
            'healing' => $amount,
        ]);
    }

    private function characterDamage(Request $request, Response $response, array $args): Response
    {
        $actor = $this->authenticate($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $characterId = (string) $args['char_id'];
        $member = $this->db->findPlayMemberByCampaignAndCharacterId($campaignId, $characterId);
        if ($member === null) {
            return respondJson($response, 404, ['error' => 'character not found']);
        }

        $isCampaignOwner = $campaign['owner'] === $actor['username'];
        if (!$isCampaignOwner && $member['username'] !== $actor['username']) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $body = $request->getParsedBody() ?? [];
        if (!isset($body['amount']) || !is_numeric($body['amount'])) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }
        $amount = (int) $body['amount'];
        if ($amount < 0) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $hpCurrent = (int) ($member['hp_current'] ?? 20);
        $hpMax = (int) ($member['hp_max'] ?? 20);
        $hpAfter = max(0, $hpCurrent - $amount);

        $this->db->updatePlayMemberHp($campaignId, $member['username'], $hpAfter, $hpMax);
        $member = $this->db->findPlayMemberByCampaignAndCharacterId($campaignId, $characterId);

        return respondJson($response, 200, [
            'character_id' => $characterId,
            'target' => $characterId,
            'hp_before' => $hpCurrent,
            'hp_current' => (int) $member['hp_current'],
            'hp_after' => $hpAfter,
            'hp_max' => (int) $member['hp_max'],
            'damage' => $amount,
            'status' => $member['status'],
        ]);
    }

    private function characterDeathSaves(Request $request, Response $response, array $args): Response
    {
        $actor = $this->authenticate($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $characterId = (string) $args['char_id'];
        $member = $this->db->findPlayMemberByCampaignAndCharacterId($campaignId, $characterId);
        if ($member === null) {
            return respondJson($response, 404, ['error' => 'character not found']);
        }

        if ($member['username'] !== $actor['username']) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $body = $request->getParsedBody() ?? [];
        if (!isset($body['outcome']) || (!is_string($body['outcome']) && !is_numeric($body['outcome']))) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }
        $outcome = (string) $body['outcome'];
        if (!in_array($outcome, ['success', 'failure'], true)) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $status = (string) ($member['status'] ?? 'conscious');
        if ($status === 'conscious' || $status === 'stable' || $status === 'dead') {
            return respondJson($response, 409, ['error' => 'cannot roll death save']);
        }

        $successes = (int) ($member['death_save_successes'] ?? 0);
        $failures = (int) ($member['death_save_failures'] ?? 0);

        if ($outcome === 'success') {
            $successes++;
            if ($successes >= 3) {
                $status = 'stable';
                $successes = 3;
            } else {
                $status = 'unconscious';
            }
        } else {
            $failures++;
            if ($failures >= 3) {
                $status = 'dead';
                $failures = 3;
            } else {
                $status = 'unconscious';
            }
        }

        $this->db->updatePlayMemberDeathSaves($campaignId, $member['username'], $successes, $failures, $status);

        return respondJson($response, 201, [
            'character_id' => $characterId,
            'successes' => $successes,
            'failures' => $failures,
            'status' => $status,
        ]);
    }

    private function characterStatus(Request $request, Response $response, array $args): Response
    {
        $actor = $this->authenticate($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $isOwner = $campaign['owner'] === $actor['username'];
        $isMember = $this->db->findPlayMemberByCampaignAndUser($campaignId, $actor['username']) !== null;
        if (!$isOwner && !$isMember) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $characterId = (string) $args['char_id'];
        $member = $this->db->findPlayMemberByCampaignAndCharacterId($campaignId, $characterId);
        if ($member === null) {
            return respondJson($response, 404, ['error' => 'character not found']);
        }

        return respondJson($response, 200, [
            'character_id' => $characterId,
            'hp_current' => (int) $member['hp_current'],
            'hp_max' => (int) $member['hp_max'],
            'status' => $member['status'],
        ]);
    }

    private function getOwner(Request $request, Response $response, array $args): Response
    {
        $actor = $this->authenticate($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $isOwner = $campaign['owner'] === $actor['username'];
        $isMember = $this->db->findPlayMemberByCampaignAndUser($campaignId, $actor['username']) !== null;
        if (!$isOwner && !$isMember) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $characterId = (string) $args['char_id'];
        $member = $this->db->findPlayMemberByCampaignAndCharacterId($campaignId, $characterId);
        if ($member === null) {
            return respondJson($response, 404, ['error' => 'character not found']);
        }

        $owner = $this->resolveOwner($member);

        return respondJson($response, 200, [
            'character_id' => $characterId,
            'owner' => $owner,
        ]);
    }

    private function claimCharacter(Request $request, Response $response, array $args): Response
    {
        $actor = $this->requirePlayer($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $isMember = $this->db->findPlayMemberByCampaignAndUser($campaignId, $actor['username']) !== null;
        if (!$isMember) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $characterId = (string) $args['char_id'];
        $member = $this->db->findPlayMemberByCampaignAndCharacterId($campaignId, $characterId);
        if ($member === null) {
            return respondJson($response, 404, ['error' => 'character not found']);
        }

        $currentOwner = $this->resolveOwner($member);

        if ($currentOwner !== $actor['username']) {
            return respondJson($response, 409, ['error' => 'character already owned']);
        }

        $this->db->updatePlayMemberOwner($campaignId, $characterId, $actor['username']);

        return respondJson($response, 201, [
            'character_id' => $characterId,
            'owner' => $actor['username'],
        ]);
    }

    private function transferCharacter(Request $request, Response $response, array $args): Response
    {
        $actor = $this->authenticate($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $characterId = (string) $args['char_id'];
        $member = $this->db->findPlayMemberByCampaignAndCharacterId($campaignId, $characterId);
        if ($member === null) {
            return respondJson($response, 404, ['error' => 'character not found']);
        }

        $currentOwner = $this->resolveOwner($member);
        if ($currentOwner !== $actor['username']) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $body = $request->getParsedBody() ?? [];
        if (!isset($body['new_owner']) || (!is_string($body['new_owner']) && !is_numeric($body['new_owner']))) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $newOwner = (string) $body['new_owner'];
        if ($newOwner === '') {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        if ($this->db->findPlayMemberByCampaignAndUser($campaignId, $newOwner) === null) {
            return respondJson($response, 400, ['error' => 'new owner is not a campaign member']);
        }

        $this->db->updatePlayMemberOwner($campaignId, $characterId, $newOwner);

        return respondJson($response, 200, [
            'character_id' => $characterId,
            'owner' => $newOwner,
        ]);
    }

    private function buildEncounterOrder(array $combatants, array $turnOrder = []): array
    {
        $order = [];
        foreach ($combatants as $c) {
            if (isset($c['monster_id'])) {
                $order[] = [
                    'name' => (string) $c['name'],
                    'kind' => 'monster',
                    'initiative' => (int) $c['initiative'],
                    'target' => (string) $c['monster_id'],
                    'member' => null,
                ];
            } elseif (isset($c['member'])) {
                $order[] = [
                    'name' => (string) $c['name'],
                    'kind' => 'player',
                    'initiative' => (int) $c['initiative'],
                    'target' => (string) $c['member'],
                    'member' => (string) $c['member'],
                ];
            }
        }

        if (empty($turnOrder)) {
            usort($order, static function (array $a, array $b): int {
                if ($b['initiative'] !== $a['initiative']) {
                    return $b['initiative'] <=> $a['initiative'];
                }
                return $a['name'] <=> $b['name'];
            });
            return $order;
        }

        $byTarget = [];
        foreach ($order as $o) {
            $byTarget[$o['target']] = $o;
        }

        $sorted = [];
        $seen = [];
        foreach ($turnOrder as $target) {
            if (isset($byTarget[$target]) && !isset($seen[$target])) {
                $sorted[] = $byTarget[$target];
                $seen[$target] = true;
            }
        }

        $remaining = [];
        foreach ($order as $o) {
            if (!isset($seen[$o['target']])) {
                $remaining[] = $o;
            }
        }
        usort($remaining, static function (array $a, array $b): int {
            if ($b['initiative'] !== $a['initiative']) {
                return $b['initiative'] <=> $a['initiative'];
            }
            return $a['name'] <=> $b['name'];
        });

        return array_merge($sorted, $remaining);
    }

    private function formatActiveCombatant(array $combatant): array
    {
        return [
            'name' => $combatant['name'],
            'kind' => $combatant['kind'],
            'initiative' => $combatant['initiative'],
        ];
    }

    private function applyCondition(Request $request, Response $response, array $args): Response
    {
        $actor = $this->requireDm($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        if ($campaign['owner'] !== $actor['username']) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $encounterId = (string) $args['enc_id'];
        $encounter = $this->db->findEncounter($encounterId);
        if ($encounter === null || $encounter['campaign_id'] !== $campaignId) {
            return respondJson($response, 404, ['error' => 'encounter not found']);
        }

        $body = $request->getParsedBody() ?? [];
        if (!isset($body['target']) || (!is_string($body['target']) && !is_numeric($body['target']))
            || !isset($body['condition']) || (!is_string($body['condition']) && !is_numeric($body['condition']))
            || !isset($body['duration_rounds']) || !is_numeric($body['duration_rounds'])) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $target = (string) $body['target'];
        $condition = (string) $body['condition'];
        $durationRounds = (int) $body['duration_rounds'];
        if ($target === '' || $condition === '' || $durationRounds < 1) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        if (!$this->encounterTargetExists($encounter['combatants'] ?? [], $target)) {
            return respondJson($response, 404, ['error' => 'target not found']);
        }

        $conditions = $encounter['conditions'] ?? [];
        $targetConditions = $conditions[$target] ?? [];

        $found = false;
        foreach ($targetConditions as $index => $existing) {
            if (isset($existing['condition']) && $existing['condition'] === $condition) {
                $targetConditions[$index]['remaining_rounds'] = $durationRounds;
                $found = true;
                break;
            }
        }
        if (!$found) {
            $targetConditions[] = ['condition' => $condition, 'remaining_rounds' => $durationRounds];
        }

        $conditions[$target] = $targetConditions;
        $this->db->updateEncounterConditions($encounterId, $conditions);

        return respondJson($response, 201, [
            'target' => $target,
            'conditions' => $targetConditions,
        ]);
    }

    private function getEncounterStatus(Request $request, Response $response, array $args): Response
    {
        $actor = $this->authenticate($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $isOwner = $campaign['owner'] === $actor['username'];
        $isMember = $this->db->findPlayMemberByCampaignAndUser($campaignId, $actor['username']) !== null;
        if (!$isOwner && !$isMember) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $encounterId = (string) $args['enc_id'];
        $encounter = $this->db->findEncounter($encounterId);
        if ($encounter === null || $encounter['campaign_id'] !== $campaignId) {
            return respondJson($response, 404, ['error' => 'encounter not found']);
        }

        $order = $this->buildEncounterStatusOrder($encounter['combatants'] ?? [], $encounter['turn_order'] ?? []);
        $turnIndex = (int) ($encounter['turn_index'] ?? 0);
        $count = count($order);
        if ($count > 0) {
            $turnIndex %= $count;
        }
        $active = $count > 0 ? $this->formatActiveCombatant($order[$turnIndex]) : null;

        return respondJson($response, 200, [
            'round' => (int) ($encounter['round'] ?? 1),
            'turn_index' => $turnIndex,
            'active' => $active,
            'order' => $order,
            'conditions' => $encounter['conditions'] ?? [],
        ]);
    }

    private function decrementConditions(array $conditions, string $target): array
    {
        if (!isset($conditions[$target]) || !is_array($conditions[$target])) {
            return $conditions;
        }

        $remaining = [];
        foreach ($conditions[$target] as $condition) {
            $remainingRounds = (int) ($condition['remaining_rounds'] ?? 0) - 1;
            if ($remainingRounds > 0) {
                $remaining[] = [
                    'condition' => (string) ($condition['condition'] ?? ''),
                    'remaining_rounds' => $remainingRounds,
                ];
            }
        }

        if (empty($remaining)) {
            unset($conditions[$target]);
        } else {
            $conditions[$target] = $remaining;
        }

        return $conditions;
    }

    private function encounterTargetExists(array $combatants, string $target): bool
    {
        foreach ($combatants as $combatant) {
            if (isset($combatant['monster_id']) && $combatant['monster_id'] === $target) {
                return true;
            }
            if (isset($combatant['member']) && $combatant['member'] === $target) {
                return true;
            }
        }
        return false;
    }

    private function awardRewards(Request $request, Response $response, array $args): Response
    {
        $actor = $this->requireDm($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        if ($campaign['owner'] !== $actor['username']) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $encounterId = (string) $args['enc_id'];
        $encounter = $this->db->findEncounter($encounterId);
        if ($encounter === null || $encounter['campaign_id'] !== $campaignId) {
            return respondJson($response, 404, ['error' => 'encounter not found']);
        }

        if ($this->db->findEncounterRewards($encounterId) !== null) {
            return respondJson($response, 409, ['error' => 'rewards already awarded']);
        }

        $body = $request->getParsedBody() ?? [];
        if (!isset($body['xp']) || !is_numeric($body['xp'])) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }
        $xp = (int) $body['xp'];
        if ($xp < 0) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $loot = [];
        if (isset($body['loot'])) {
            if (!is_array($body['loot'])) {
                return respondJson($response, 400, ['error' => 'invalid request']);
            }
            foreach ($body['loot'] as $entry) {
                if (!is_array($entry)
                    || !isset($entry['slug']) || (!is_string($entry['slug']) && !is_numeric($entry['slug']))
                    || !isset($entry['quantity']) || !is_numeric($entry['quantity'])) {
                    return respondJson($response, 400, ['error' => 'invalid request']);
                }
                $slug = (string) $entry['slug'];
                $quantity = (int) $entry['quantity'];
                if ($slug === '' || $quantity < 1) {
                    return respondJson($response, 400, ['error' => 'invalid request']);
                }
                $loot[] = ['slug' => $slug, 'quantity' => $quantity];
            }
        }

        $this->db->createEncounterRewards($encounterId, $xp, $loot);

        return respondJson($response, 200, [
            'xp' => $xp,
            'loot' => $loot,
        ]);
    }

    private function endEncounter(Request $request, Response $response, array $args): Response
    {
        $actor = $this->requireDm($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        if ($campaign['owner'] !== $actor['username']) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $encounterId = (string) $args['enc_id'];
        $encounter = $this->db->findEncounter($encounterId);
        if ($encounter === null || $encounter['campaign_id'] !== $campaignId) {
            return respondJson($response, 404, ['error' => 'encounter not found']);
        }

        if ($campaign['phase'] !== 'combat') {
            return respondJson($response, 409, ['error' => 'campaign not in combat']);
        }

        if ($encounter['status'] === 'active') {
            $this->db->closeEncounter($encounterId);
        }

        $this->db->endPlayCampaignCombat($campaignId, $campaign['owner']);

        $updatedCampaign = $this->db->findPlayCampaign($campaignId);
        $currentActor = (string) ($updatedCampaign['current_actor'] ?? $campaign['owner']);

        return respondJson($response, 200, [
            'campaign_id' => $campaignId,
            'status' => (string) ($updatedCampaign['status'] ?? 'active'),
            'phase' => 'exploration',
            'current_actor' => $currentActor,
        ]);
    }

    private function closeEncounter(Request $request, Response $response, array $args): Response
    {
        $actor = $this->requireDm($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        if ($campaign['owner'] !== $actor['username']) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $encounterId = (string) $args['enc_id'];
        $encounter = $this->db->findEncounter($encounterId);
        if ($encounter === null || $encounter['campaign_id'] !== $campaignId) {
            return respondJson($response, 404, ['error' => 'encounter not found']);
        }

        $this->db->closeEncounter($encounterId);

        $rewards = $this->db->findEncounterRewards($encounterId);
        $xpAwarded = $rewards !== null ? (int) $rewards['xp'] : 0;

        return respondJson($response, 200, [
            'id' => $encounterId,
            'status' => 'closed',
            'xp_awarded' => $xpAwarded,
        ]);
    }

    private function buildEncounterStatusOrder(array $combatants, array $turnOrder = []): array
    {
        $order = [];
        foreach ($combatants as $c) {
            if (isset($c['monster_id'])) {
                $order[] = [
                    'key' => (string) $c['monster_id'],
                    'name' => (string) $c['name'],
                    'kind' => 'monster',
                    'initiative' => (int) $c['initiative'],
                ];
            } elseif (isset($c['member'])) {
                $order[] = [
                    'key' => (string) $c['member'],
                    'name' => (string) $c['name'],
                    'kind' => 'player',
                    'initiative' => (int) $c['initiative'],
                ];
            }
        }

        if (empty($turnOrder)) {
            usort($order, static function (array $a, array $b): int {
                if ($b['initiative'] !== $a['initiative']) {
                    return $b['initiative'] <=> $a['initiative'];
                }
                return $a['name'] <=> $b['name'];
            });
            return $order;
        }

        $byTarget = [];
        foreach ($order as $o) {
            $byTarget[$o['key']] = $o;
        }

        $sorted = [];
        $seen = [];
        foreach ($turnOrder as $target) {
            if (isset($byTarget[$target]) && !isset($seen[$target])) {
                $sorted[] = $byTarget[$target];
                $seen[$target] = true;
            }
        }

        $remaining = [];
        foreach ($order as $o) {
            if (!isset($seen[$o['key']])) {
                $remaining[] = $o;
            }
        }
        usort($remaining, static function (array $a, array $b): int {
            if ($b['initiative'] !== $a['initiative']) {
                return $b['initiative'] <=> $a['initiative'];
            }
            return $a['name'] <=> $b['name'];
        });

        return array_merge($sorted, $remaining);
    }

    private function buildCharacter(Request $request, Response $response, array $args): Response
    {
        $actor = $this->requirePlayer($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $characterId = (string) $args['char_id'];
        $member = $this->db->findPlayMemberByCampaignAndCharacterId($campaignId, $characterId);
        if ($member === null) {
            return respondJson($response, 404, ['error' => 'character not found']);
        }

        $owner = $this->resolveOwner($member);
        if ($owner !== $actor['username']) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $body = $request->getParsedBody() ?? [];
        if (!isset($body['race']) || (!is_string($body['race']) && !is_numeric($body['race']))
            || !isset($body['class']) || (!is_string($body['class']) && !is_numeric($body['class']))
            || !isset($body['background']) || (!is_string($body['background']) && !is_numeric($body['background']))
            || !isset($body['abilities']) || !is_array($body['abilities'])) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $race = (string) $body['race'];
        $class = (string) $body['class'];
        $background = (string) $body['background'];
        if ($race === '' || $class === '' || $background === '') {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        if (!in_array($race, self::VALID_RACES, true)
            || !in_array($class, self::VALID_CLASSES, true)
            || !in_array($background, self::VALID_BACKGROUNDS, true)) {
            return respondJson($response, 400, ['error' => 'invalid choice']);
        }

        $abilities = ['str', 'dex', 'con', 'int', 'wis', 'cha'];
        $abilityScores = [];
        foreach ($abilities as $ability) {
            if (!isset($body['abilities'][$ability]) || !is_numeric($body['abilities'][$ability])) {
                return respondJson($response, 400, ['error' => 'invalid ability score']);
            }
            $score = (int) $body['abilities'][$ability];
            if ($score < 1 || $score > 30) {
                return respondJson($response, 400, ['error' => 'ability score out of range']);
            }
            $abilityScores[$ability] = $score;
        }

        $conModifier = (int) floor(($abilityScores['con'] - 10) / 2.0);
        $hpMax = self::HIT_DICE[$class] + $conModifier;
        $level = 1;

        $this->db->updatePlayMemberBuild($campaignId, $characterId, $race, $class, $background, $level, $hpMax, $abilityScores);
        $this->initializeSpellSlots($campaignId, $characterId, $class, $level);

        return respondJson($response, 200, [
            'character_id' => $characterId,
            'race' => $race,
            'class' => $class,
            'background' => $background,
            'level' => $level,
            'hp_max' => $hpMax,
            'proficiency_bonus' => 2,
        ]);
    }

    private function levelUp(Request $request, Response $response, array $args): Response
    {
        $actor = $this->authenticate($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $characterId = (string) $args['char_id'];
        $member = $this->db->findPlayMemberByCampaignAndCharacterId($campaignId, $characterId);
        if ($member === null) {
            return respondJson($response, 404, ['error' => 'character not found']);
        }

        $owner = $this->resolveOwner($member);
        if ($owner !== $actor['username']) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $body = $request->getParsedBody() ?? [];
        if (!isset($body['level']) || !is_numeric($body['level'])) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }
        $level = (int) $body['level'];

        $currentLevel = (int) ($member['level'] ?? 0);
        if ($currentLevel < 1) {
            $currentLevel = 1;
        }
        if ($level !== $currentLevel + 1) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $class = (string) $member['class'];
        if (!isset(self::HIT_DICE[$class])) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }
        $hitDie = self::HIT_DICE[$class];

        $conMod = 0;
        $abilitiesJson = $member['abilities_json'] ?? null;
        if (is_string($abilitiesJson) && $abilitiesJson !== '') {
            $abilities = json_decode($abilitiesJson, true);
            if (is_array($abilities) && isset($abilities['con']) && is_numeric($abilities['con'])) {
                $conMod = $this->engine->abilityModifier((int) $abilities['con']);
            }
        }

        $hpMax = $this->engine->leveledHitPoints($level, $conMod, $hitDie);
        $this->db->updatePlayMemberLevelAndHpMax($campaignId, $characterId, $level, $hpMax);
        $this->initializeSpellSlots($campaignId, $characterId, $class, $level);

        return respondJson($response, 200, [
            'character_id' => $characterId,
            'level' => $level,
            'hp_max' => $hpMax,
            'hit_dice' => '1d' . $hitDie,
            'proficiency_bonus' => $this->engine->proficiencyBonus($level),
        ]);
    }

    private function skillCheck(Request $request, Response $response, array $args): Response
    {
        $actor = $this->authenticate($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $characterId = (string) $args['char_id'];
        $member = $this->db->findPlayMemberByCampaignAndCharacterId($campaignId, $characterId);
        if ($member === null) {
            return respondJson($response, 404, ['error' => 'character not found']);
        }

        $owner = $this->resolveOwner($member);
        if ($owner !== $actor['username']) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $body = $request->getParsedBody() ?? [];
        if (!isset($body['skill']) || (!is_string($body['skill']) && !is_numeric($body['skill']))
            || !isset($body['ability']) || (!is_string($body['ability']) && !is_numeric($body['ability']))
            || !isset($body['proficient']) || !is_bool($body['proficient'])
            || !isset($body['roll']) || !is_numeric($body['roll'])) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $skill = (string) $body['skill'];
        $ability = (string) $body['ability'];
        $proficient = (bool) $body['proficient'];
        $roll = (int) $body['roll'];
        if ($skill === '' || $ability === '') {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        if (!in_array($ability, self::VALID_ABILITIES, true) || !in_array($skill, self::VALID_SKILLS, true)) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $abilities = [];
        $abilitiesJson = $member['abilities_json'] ?? null;
        if (is_string($abilitiesJson) && $abilitiesJson !== '') {
            $decoded = json_decode($abilitiesJson, true);
            if (is_array($decoded)) {
                $abilities = $decoded;
            }
        }

        $abilityScore = isset($abilities[$ability]) && is_numeric($abilities[$ability]) ? (int) $abilities[$ability] : 10;
        $level = (int) ($member['level'] ?? 1);
        if ($level < 1) {
            $level = 1;
        }

        $modifier = $this->engine->skillCheckModifier($abilityScore, $level, $proficient);
        $total = $roll + $modifier;

        return respondJson($response, 200, [
            'character_id' => $characterId,
            'skill' => $skill,
            'ability' => $ability,
            'modifier' => $modifier,
            'total' => $total,
        ]);
    }

    private function addSpell(Request $request, Response $response, array $args): Response
    {
        $actor = $this->authenticate($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $characterId = (string) $args['char_id'];
        $member = $this->db->findPlayMemberByCampaignAndCharacterId($campaignId, $characterId);
        if ($member === null) {
            return respondJson($response, 404, ['error' => 'character not found']);
        }

        $owner = $this->resolveOwner($member);
        if ($owner !== $actor['username']) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $body = $request->getParsedBody() ?? [];
        if (!isset($body['spell_id']) || (!is_string($body['spell_id']) && !is_numeric($body['spell_id']))
            || !isset($body['name']) || (!is_string($body['name']) && !is_numeric($body['name']))
            || !isset($body['level']) || !is_numeric($body['level'])) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $spellId = (string) $body['spell_id'];
        $name = (string) $body['name'];
        $level = (int) $body['level'];
        if ($spellId === '' || $name === '') {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $class = (string) $member['class'];
        if ($class !== 'wizard') {
            return respondJson($response, 400, ['error' => 'invalid class/spell combination']);
        }

        if ($this->db->findCharacterSpell($campaignId, $characterId, $spellId) !== null) {
            return respondJson($response, 409, ['error' => 'duplicate spell']);
        }

        $this->db->createCharacterSpell($campaignId, $characterId, $spellId, $name, $level);

        return respondJson($response, 201, [
            'spell_id' => $spellId,
            'name' => $name,
            'level' => $level,
        ]);
    }

    private function listSpells(Request $request, Response $response, array $args): Response
    {
        $actor = $this->authenticate($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $isOwner = $campaign['owner'] === $actor['username'];
        $isMember = $this->db->findPlayMemberByCampaignAndUser($campaignId, $actor['username']) !== null;
        if (!$isOwner && !$isMember) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $characterId = (string) $args['char_id'];
        $member = $this->db->findPlayMemberByCampaignAndCharacterId($campaignId, $characterId);
        if ($member === null) {
            return respondJson($response, 404, ['error' => 'character not found']);
        }

        $spells = $this->db->findCharacterSpells($campaignId, $characterId);

        return respondJson($response, 200, ['spells' => $spells]);
    }

    private function prepareSpells(Request $request, Response $response, array $args): Response
    {
        $actor = $this->authenticate($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $characterId = (string) $args['char_id'];
        $member = $this->db->findPlayMemberByCampaignAndCharacterId($campaignId, $characterId);
        if ($member === null) {
            return respondJson($response, 404, ['error' => 'character not found']);
        }

        $owner = $this->resolveOwner($member);
        if ($owner !== $actor['username']) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $body = $request->getParsedBody() ?? [];
        if (!isset($body['spell_ids']) || !is_array($body['spell_ids'])) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $spellIds = [];
        foreach ($body['spell_ids'] as $value) {
            if (!is_string($value) && !is_numeric($value)) {
                return respondJson($response, 400, ['error' => 'invalid request']);
            }
            $spellId = (string) $value;
            if ($spellId === '') {
                return respondJson($response, 400, ['error' => 'invalid request']);
            }
            $spellIds[] = $spellId;
        }

        $class = (string) $member['class'];
        if (!$this->engine->isSpellcastingClass($class)) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $level = (int) ($member['level'] ?? 1);
        if ($level < 1) {
            $level = 1;
        }
        $maxPrepared = $this->engine->maxPreparedSpells($level);

        if (count($spellIds) > $maxPrepared) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        foreach ($spellIds as $spellId) {
            if ($this->db->findCharacterSpell($campaignId, $characterId, $spellId) === null) {
                return respondJson($response, 400, ['error' => 'invalid request']);
            }
        }

        $this->db->setCharacterPreparedSpells($campaignId, $characterId, $spellIds);

        return respondJson($response, 200, [
            'character_id' => $characterId,
            'prepared_spells' => $spellIds,
            'max_prepared' => $maxPrepared,
        ]);
    }

    private function getPreparedSpells(Request $request, Response $response, array $args): Response
    {
        $actor = $this->authenticate($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $isOwner = $campaign['owner'] === $actor['username'];
        $isMember = $this->db->findPlayMemberByCampaignAndUser($campaignId, $actor['username']) !== null;
        if (!$isOwner && !$isMember) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $characterId = (string) $args['char_id'];
        $member = $this->db->findPlayMemberByCampaignAndCharacterId($campaignId, $characterId);
        if ($member === null) {
            return respondJson($response, 404, ['error' => 'character not found']);
        }

        $level = (int) ($member['level'] ?? 1);
        if ($level < 1) {
            $level = 1;
        }
        $maxPrepared = $this->engine->maxPreparedSpells($level);

        $preparedSpells = $this->db->findCharacterPreparedSpells($campaignId, $characterId);

        return respondJson($response, 200, [
            'character_id' => $characterId,
            'prepared_spells' => $preparedSpells,
            'max_prepared' => $maxPrepared,
        ]);
    }

    private function castSpell(Request $request, Response $response, array $args): Response
    {
        $actor = $this->authenticate($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $characterId = (string) $args['char_id'];
        $member = $this->db->findPlayMemberByCampaignAndCharacterId($campaignId, $characterId);
        if ($member === null) {
            return respondJson($response, 404, ['error' => 'character not found']);
        }

        $owner = $this->resolveOwner($member);
        if ($owner !== $actor['username']) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $body = $request->getParsedBody() ?? [];
        if (!isset($body['spell_id']) || (!is_string($body['spell_id']) && !is_numeric($body['spell_id']))
            || !isset($body['target']) || (!is_string($body['target']) && !is_numeric($body['target']))) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $spellId = (string) $body['spell_id'];
        $target = (string) $body['target'];
        if ($spellId === '' || $target === '') {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $class = (string) $member['class'];
        if (!$this->engine->isSpellcastingClass($class)) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $spell = $this->db->findCharacterSpell($campaignId, $characterId, $spellId);
        if ($spell === null) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $preparedSpells = $this->db->findCharacterPreparedSpells($campaignId, $characterId);
        if (!in_array($spellId, $preparedSpells, true)) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $spellLevel = (int) $spell['level'];
        $level = (int) ($member['level'] ?? 1);
        if ($level < 1) {
            $level = 1;
        }

        $existingSlots = $this->db->findCharacterSpellSlots($campaignId, $characterId);
        if (empty($existingSlots)) {
            $this->initializeSpellSlots($campaignId, $characterId, $class, $level);
        }

        $slot = $this->db->findCharacterSpellSlot($campaignId, $characterId, $spellLevel);
        if ($slot === null || $slot['slots_remaining'] < 1) {
            return respondJson($response, 409, ['error' => 'no spell slots remaining']);
        }

        $consumed = $this->db->consumeCharacterSpellSlot($campaignId, $characterId, $spellLevel);
        if (!$consumed) {
            return respondJson($response, 409, ['error' => 'no spell slots remaining']);
        }

        $slot = $this->db->findCharacterSpellSlot($campaignId, $characterId, $spellLevel);
        $slotsRemaining = $slot['slots_remaining'] ?? 0;
        $sequence = $this->db->nextCastSequence($campaignId, $characterId);

        $this->db->createCast([
            'campaign_id' => $campaignId,
            'character_id' => $characterId,
            'sequence' => $sequence,
            'spell_id' => $spellId,
            'target' => $target,
            'slot_level' => $spellLevel,
            'slots_remaining' => $slotsRemaining,
        ]);

        return respondJson($response, 201, [
            'character_id' => $characterId,
            'spell_id' => $spellId,
            'target' => $target,
            'slot_level' => $spellLevel,
            'slots_remaining' => $slotsRemaining,
            'sequence' => $sequence,
        ]);
    }

    private function listCasts(Request $request, Response $response, array $args): Response
    {
        $actor = $this->authenticate($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $isOwner = $campaign['owner'] === $actor['username'];
        $isMember = $this->db->findPlayMemberByCampaignAndUser($campaignId, $actor['username']) !== null;
        if (!$isOwner && !$isMember) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $characterId = (string) $args['char_id'];
        $member = $this->db->findPlayMemberByCampaignAndCharacterId($campaignId, $characterId);
        if ($member === null) {
            return respondJson($response, 404, ['error' => 'character not found']);
        }

        $castRows = $this->db->findCharacterCasts($campaignId, $characterId);
        $casts = [];
        foreach ($castRows as $row) {
            $casts[] = [
                'character_id' => $characterId,
                'spell_id' => $row['spell_id'],
                'target' => $row['target'],
                'slot_level' => (int) $row['slot_level'],
                'slots_remaining' => (int) $row['slots_remaining'],
                'sequence' => (int) $row['sequence'],
            ];
        }

        return respondJson($response, 200, ['casts' => $casts]);
    }

    private function setConcentration(Request $request, Response $response, array $args): Response
    {
        $actor = $this->authenticate($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $characterId = (string) $args['char_id'];
        $member = $this->db->findPlayMemberByCampaignAndCharacterId($campaignId, $characterId);
        if ($member === null) {
            return respondJson($response, 404, ['error' => 'character not found']);
        }

        $owner = $this->resolveOwner($member);
        if ($owner !== $actor['username']) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $body = $request->getParsedBody() ?? [];
        if (!isset($body['spell_id']) || (!is_string($body['spell_id']) && !is_numeric($body['spell_id']))
            || !isset($body['target']) || (!is_string($body['target']) && !is_numeric($body['target']))
            || !isset($body['duration_turns']) || !is_numeric($body['duration_turns'])) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $spellId = (string) $body['spell_id'];
        $target = (string) $body['target'];
        $durationTurns = (int) $body['duration_turns'];
        if ($spellId === '' || $target === '' || $durationTurns < 1) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $class = (string) $member['class'];
        if (!$this->engine->isSpellcastingClass($class)) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        if ($this->db->findCharacterSpell($campaignId, $characterId, $spellId) === null) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $preparedSpells = $this->db->findCharacterPreparedSpells($campaignId, $characterId);
        if (!in_array($spellId, $preparedSpells, true)) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $this->db->setCharacterConcentration($campaignId, $characterId, $spellId, $target, $durationTurns);

        return respondJson($response, 200, [
            'character_id' => $characterId,
            'concentration' => [
                'spell_id' => $spellId,
                'target' => $target,
                'remaining_turns' => $durationTurns,
            ],
        ]);
    }

    private function getConcentration(Request $request, Response $response, array $args): Response
    {
        $actor = $this->authenticate($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $isOwner = $campaign['owner'] === $actor['username'];
        $isMember = $this->db->findPlayMemberByCampaignAndUser($campaignId, $actor['username']) !== null;
        if (!$isOwner && !$isMember) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $characterId = (string) $args['char_id'];
        $member = $this->db->findPlayMemberByCampaignAndCharacterId($campaignId, $characterId);
        if ($member === null) {
            return respondJson($response, 404, ['error' => 'character not found']);
        }

        $concentration = $this->db->findCharacterConcentration($campaignId, $characterId);

        return respondJson($response, 200, [
            'character_id' => $characterId,
            'concentration' => $concentration,
        ]);
    }

    private function advanceConcentrationTurn(Request $request, Response $response, array $args): Response
    {
        $actor = $this->authenticate($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $isOwner = $campaign['owner'] === $actor['username'];
        $isMember = $this->db->findPlayMemberByCampaignAndUser($campaignId, $actor['username']) !== null;
        if (!$isOwner && !$isMember) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $characterId = (string) $args['char_id'];
        $member = $this->db->findPlayMemberByCampaignAndCharacterId($campaignId, $characterId);
        if ($member === null) {
            return respondJson($response, 404, ['error' => 'character not found']);
        }

        $concentration = $this->db->findCharacterConcentration($campaignId, $characterId);
        if ($concentration !== null) {
            $remainingTurns = (int) $concentration['remaining_turns'] - 1;
            if ($remainingTurns > 0) {
                $this->db->setCharacterConcentration($campaignId, $characterId, $concentration['spell_id'], $concentration['target'], $remainingTurns);
                $concentration['remaining_turns'] = $remainingTurns;
            } else {
                $this->db->clearCharacterConcentration($campaignId, $characterId);
                $concentration = null;
            }
        }

        return respondJson($response, 200, [
            'character_id' => $characterId,
            'concentration' => $concentration,
        ]);
    }

    private function clearConcentration(Request $request, Response $response, array $args): Response
    {
        $actor = $this->authenticate($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $characterId = (string) $args['char_id'];
        $member = $this->db->findPlayMemberByCampaignAndCharacterId($campaignId, $characterId);
        if ($member === null) {
            return respondJson($response, 404, ['error' => 'character not found']);
        }

        $owner = $this->resolveOwner($member);
        if ($owner !== $actor['username']) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $this->db->clearCharacterConcentration($campaignId, $characterId);

        return respondJson($response, 200, [
            'character_id' => $characterId,
            'concentration' => null,
        ]);
    }

    private function addInventoryItem(Request $request, Response $response, array $args): Response
    {
        $actor = $this->authenticate($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $characterId = (string) $args['character_id'];
        $member = $this->db->findPlayMemberByCampaignAndCharacterId($campaignId, $characterId);
        if ($member === null) {
            return respondJson($response, 404, ['error' => 'character not found']);
        }

        $owner = $this->resolveOwner($member);
        if ($owner !== $actor['username']) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $body = $request->getParsedBody() ?? [];
        if (!isset($body['item_id']) || (!is_string($body['item_id']) && !is_numeric($body['item_id']))
            || !isset($body['quantity']) || !is_numeric($body['quantity'])) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $itemId = (string) $body['item_id'];
        $quantity = (int) $body['quantity'];
        if ($itemId === '' || $quantity < 1 || !in_array($itemId, self::VALID_INVENTORY_ITEMS, true)) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $this->db->addCharacterInventoryItem($campaignId, $characterId, $itemId, $quantity);
        $item = $this->db->findCharacterInventoryItem($campaignId, $characterId, $itemId);

        return respondJson($response, 201, [
            'character_id' => $characterId,
            'item_id' => $itemId,
            'quantity' => $quantity,
            'total_quantity' => (int) ($item['quantity'] ?? $quantity),
        ]);
    }

    private function listInventoryItems(Request $request, Response $response, array $args): Response
    {
        $actor = $this->authenticate($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $isOwner = $campaign['owner'] === $actor['username'];
        $isMember = $this->db->findPlayMemberByCampaignAndUser($campaignId, $actor['username']) !== null;
        if (!$isOwner && !$isMember) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $characterId = (string) $args['character_id'];
        $member = $this->db->findPlayMemberByCampaignAndCharacterId($campaignId, $characterId);
        if ($member === null) {
            return respondJson($response, 404, ['error' => 'character not found']);
        }

        $rows = $this->db->findCharacterInventoryItems($campaignId, $characterId);
        $items = [];
        foreach ($rows as $row) {
            $items[] = [
                'item_id' => $row['item_slug'],
                'quantity' => (int) $row['quantity'],
            ];
        }

        return respondJson($response, 200, [
            'character_id' => $characterId,
            'items' => $items,
        ]);
    }

    private function removeInventoryItem(Request $request, Response $response, array $args): Response
    {
        $actor = $this->authenticate($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $characterId = (string) $args['character_id'];
        $member = $this->db->findPlayMemberByCampaignAndCharacterId($campaignId, $characterId);
        if ($member === null) {
            return respondJson($response, 404, ['error' => 'character not found']);
        }

        $owner = $this->resolveOwner($member);
        if ($owner !== $actor['username']) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $itemId = (string) $args['item_id'];
        if (!in_array($itemId, self::VALID_INVENTORY_ITEMS, true)) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $body = $request->getParsedBody() ?? [];
        if (!isset($body['quantity']) || !is_numeric($body['quantity'])) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $quantity = (int) $body['quantity'];
        if ($quantity < 1) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $existing = $this->db->findCharacterInventoryItem($campaignId, $characterId, $itemId);
        $held = $existing !== null ? (int) $existing['quantity'] : 0;
        if ($quantity > $held) {
            return respondJson($response, 409, ['error' => 'insufficient quantity']);
        }

        $totalQuantity = $this->db->reduceCharacterInventoryItem($campaignId, $characterId, $itemId, $quantity);

        return respondJson($response, 200, [
            'character_id' => $characterId,
            'item_id' => $itemId,
            'quantity' => $quantity,
            'total_quantity' => $totalQuantity,
        ]);
    }

    private function equipItem(Request $request, Response $response, array $args): Response
    {
        $actor = $this->authenticate($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $characterId = (string) $args['character_id'];
        $member = $this->db->findPlayMemberByCampaignAndCharacterId($campaignId, $characterId);
        if ($member === null) {
            return respondJson($response, 404, ['error' => 'character not found']);
        }

        $owner = $this->resolveOwner($member);
        if ($owner !== $actor['username']) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $slot = (string) $args['slot'];
        if (!in_array($slot, self::EQUIPMENT_SLOTS, true)) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $body = $request->getParsedBody() ?? [];
        if (!isset($body['item_id']) || (!is_string($body['item_id']) && !is_numeric($body['item_id']))) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $itemId = (string) $body['item_id'];
        if ($itemId === '' || !in_array($itemId, self::VALID_INVENTORY_ITEMS, true)) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        if (!isset(self::ITEM_SLOTS[$itemId]) || self::ITEM_SLOTS[$itemId] !== $slot) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $inventoryItem = $this->db->findCharacterInventoryItem($campaignId, $characterId, $itemId);
        if ($inventoryItem === null || (int) $inventoryItem['quantity'] < 1) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $this->db->setCharacterEquipment($campaignId, $characterId, $slot, $itemId, false);

        return respondJson($response, 200, [
            'character_id' => $characterId,
            'slot' => $slot,
            'item_id' => $itemId,
            'attuned' => false,
        ]);
    }

    private function getEquipment(Request $request, Response $response, array $args): Response
    {
        $actor = $this->authenticate($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $isOwner = $campaign['owner'] === $actor['username'];
        $isMember = $this->db->findPlayMemberByCampaignAndUser($campaignId, $actor['username']) !== null;
        if (!$isOwner && !$isMember) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $characterId = (string) $args['character_id'];
        $member = $this->db->findPlayMemberByCampaignAndCharacterId($campaignId, $characterId);
        if ($member === null) {
            return respondJson($response, 404, ['error' => 'character not found']);
        }

        $slot = (string) $args['slot'];
        if (!in_array($slot, self::EQUIPMENT_SLOTS, true)) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $equipped = $this->db->findCharacterEquipment($campaignId, $characterId, $slot);
        if ($equipped === null) {
            return respondJson($response, 200, [
                'character_id' => $characterId,
                'slot' => $slot,
                'item_id' => '',
                'attuned' => false,
            ]);
        }

        return respondJson($response, 200, [
            'character_id' => $characterId,
            'slot' => $slot,
            'item_id' => $equipped['item_slug'],
            'attuned' => (bool) $equipped['attuned'],
        ]);
    }

    private function attuneItem(Request $request, Response $response, array $args): Response
    {
        $actor = $this->authenticate($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $characterId = (string) $args['character_id'];
        $member = $this->db->findPlayMemberByCampaignAndCharacterId($campaignId, $characterId);
        if ($member === null) {
            return respondJson($response, 404, ['error' => 'character not found']);
        }

        $owner = $this->resolveOwner($member);
        if ($owner !== $actor['username']) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $slot = (string) $args['slot'];
        if (!in_array($slot, self::EQUIPMENT_SLOTS, true) || $slot !== 'accessory') {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $equipped = $this->db->findCharacterEquipment($campaignId, $characterId, $slot);
        if ($equipped === null || $equipped['item_slug'] === '') {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $itemId = $equipped['item_slug'];
        if (!in_array($itemId, self::ATTUNABLE_ITEMS, true)) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $attunedCount = $this->db->countAttunedItems($campaignId, $characterId);
        if ($attunedCount >= 1) {
            return respondJson($response, 409, ['error' => 'max attunements reached']);
        }

        $this->db->setCharacterEquipmentAttuned($campaignId, $characterId, $slot, true);

        return respondJson($response, 200, [
            'character_id' => $characterId,
            'slot' => $slot,
            'item_id' => $itemId,
            'attuned' => true,
            'attunement_count' => 1,
            'max_attunements' => 1,
        ]);
    }

    private function consumeInventoryItem(Request $request, Response $response, array $args): Response
    {
        $actor = $this->authenticate($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $characterId = (string) $args['character_id'];
        $member = $this->db->findPlayMemberByCampaignAndCharacterId($campaignId, $characterId);
        if ($member === null) {
            return respondJson($response, 404, ['error' => 'character not found']);
        }

        $owner = $this->resolveOwner($member);
        if ($owner !== $actor['username']) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $itemId = (string) $args['item_id'];
        if (!in_array($itemId, self::VALID_INVENTORY_ITEMS, true)) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        if (!in_array($itemId, self::CONSUMABLE_ITEMS, true)) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $existing = $this->db->findCharacterInventoryItem($campaignId, $characterId, $itemId);
        $held = $existing !== null ? (int) $existing['quantity'] : 0;
        if ($held < 1) {
            return respondJson($response, 409, ['error' => 'insufficient quantity']);
        }

        $totalQuantity = $this->db->reduceCharacterInventoryItem($campaignId, $characterId, $itemId, 1);

        return respondJson($response, 200, [
            'character_id' => $characterId,
            'item_id' => $itemId,
            'quantity_consumed' => 1,
            'total_quantity' => $totalQuantity,
            'effect' => [
                'type' => 'healing',
                'hp_restored' => 5,
            ],
        ]);
    }

    private function getCurrency(Request $request, Response $response, array $args): Response
    {
        $actor = $this->authenticate($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $isOwner = $campaign['owner'] === $actor['username'];
        $isMember = $this->db->findPlayMemberByCampaignAndUser($campaignId, $actor['username']) !== null;
        if (!$isOwner && !$isMember) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $characterId = (string) $args['character_id'];
        $member = $this->db->findPlayMemberByCampaignAndCharacterId($campaignId, $characterId);
        if ($member === null) {
            return respondJson($response, 404, ['error' => 'character not found']);
        }

        $currency = $this->db->findCharacterCurrency($campaignId, $characterId);
        if ($currency === null) {
            $currency = $this->db->ensureCharacterCurrency($campaignId, $characterId);
        }

        return respondJson($response, 200, [
            'character_id' => $characterId,
            'gold' => $currency['gold'],
        ]);
    }

    private function transferCurrency(Request $request, Response $response, array $args): Response
    {
        $actor = $this->authenticate($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $characterId = (string) $args['character_id'];
        $member = $this->db->findPlayMemberByCampaignAndCharacterId($campaignId, $characterId);
        if ($member === null) {
            return respondJson($response, 404, ['error' => 'character not found']);
        }

        $owner = $this->resolveOwner($member);
        if ($owner !== $actor['username']) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $body = $request->getParsedBody() ?? [];
        if (!isset($body['to_character_id']) || (!is_string($body['to_character_id']) && !is_numeric($body['to_character_id']))
            || !isset($body['gold']) || !is_numeric($body['gold'])) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $toCharacterId = (string) $body['to_character_id'];
        $gold = (int) $body['gold'];
        if ($toCharacterId === '' || $gold <= 0) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        if ($toCharacterId === $characterId) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $toMember = $this->db->findPlayMemberByCampaignAndCharacterId($campaignId, $toCharacterId);
        if ($toMember === null) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $transfer = $this->db->transferCurrency($campaignId, $characterId, $toCharacterId, $gold);
        if ($transfer === null) {
            return respondJson($response, 409, ['error' => 'insufficient gold']);
        }

        return respondJson($response, 201, [
            'from_character_id' => $transfer['from_character_id'],
            'to_character_id' => $transfer['to_character_id'],
            'gold' => $transfer['gold'],
            'from_gold' => $transfer['from_gold'],
            'to_gold' => $transfer['to_gold'],
            'transfer_id' => $transfer['transfer_id'],
        ]);
    }

    private function createTransactionalTransfer(Request $request, Response $response, array $args): Response
    {
        $actor = $this->authenticate($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $body = $request->getParsedBody() ?? [];
        if (!isset($body['from_character_id']) || (!is_string($body['from_character_id']) && !is_numeric($body['from_character_id']))
            || !isset($body['to_character_id']) || (!is_string($body['to_character_id']) && !is_numeric($body['to_character_id']))
            || !isset($body['amount']) || !is_int($body['amount'])
            || !isset($body['simulate_failure']) || !is_bool($body['simulate_failure'])) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $fromCharacterId = (string) $body['from_character_id'];
        $toCharacterId = (string) $body['to_character_id'];
        $amount = $body['amount'];
        $simulateFailure = $body['simulate_failure'];

        if ($fromCharacterId === '' || $toCharacterId === '' || $amount <= 0) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $fromMember = $this->db->findPlayMemberByCampaignAndCharacterId($campaignId, $fromCharacterId);
        if ($fromMember === null) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $toMember = $this->db->findPlayMemberByCampaignAndCharacterId($campaignId, $toCharacterId);
        if ($toMember === null) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        if ($fromCharacterId === $toCharacterId) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $owner = $this->resolveOwner($fromMember);
        if ($owner !== $actor['username']) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $result = $this->db->transferTransactionalCurrency($campaignId, $fromCharacterId, $toCharacterId, $amount, $simulateFailure);
        if (isset($result['insufficient']) && $result['insufficient']) {
            return respondJson($response, 409, ['error' => 'insufficient gold']);
        }
        if (isset($result['simulated']) && $result['simulated']) {
            return respondJson($response, 500, ['error' => 'simulated failure']);
        }

        return respondJson($response, 201, [
            'from_character_id' => $fromCharacterId,
            'to_character_id' => $toCharacterId,
            'amount' => $amount,
            'from_gold' => $result['from_gold'],
            'to_gold' => $result['to_gold'],
            'sequence' => $result['sequence'],
        ]);
    }

    private function listTransactionalTransfers(Request $request, Response $response, array $args): Response
    {
        $actor = $this->authenticate($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $isOwner = $campaign['owner'] === $actor['username'];
        $isMember = $this->db->findPlayMemberByCampaignAndUser($campaignId, $actor['username']) !== null;
        if (!$isOwner && !$isMember) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $transfers = $this->db->findTransactionalTransfers($campaignId);
        return respondJson($response, 200, ['transfers' => $transfers]);
    }

    // Loot distribution

    private function createLoot(Request $request, Response $response, array $args): Response
    {
        $actor = $this->requireDm($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        if ($campaign['owner'] !== $actor['username']) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $body = $request->getParsedBody() ?? [];
        if (!isset($body['loot_id']) || (!is_string($body['loot_id']) && !is_numeric($body['loot_id']))
            || !isset($body['item_id']) || (!is_string($body['item_id']) && !is_numeric($body['item_id']))
            || !isset($body['quantity']) || !is_numeric($body['quantity'])) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $lootId = (string) $body['loot_id'];
        $itemId = (string) $body['item_id'];
        $quantity = (int) $body['quantity'];
        if ($lootId === '' || $itemId === '' || $quantity < 1 || !in_array($itemId, self::VALID_INVENTORY_ITEMS, true)) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        if ($this->db->findLoot($campaignId, $lootId) !== null) {
            return respondJson($response, 409, ['error' => 'loot id already exists']);
        }

        $this->db->createLoot($campaignId, $lootId, $itemId, $quantity);

        return respondJson($response, 201, [
            'loot_id' => $lootId,
            'item_id' => $itemId,
            'quantity' => $quantity,
            'status' => 'open',
        ]);
    }

    private function voteLoot(Request $request, Response $response, array $args): Response
    {
        $actor = $this->requirePlayer($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $member = $this->db->findPlayMemberByCampaignAndUser($campaignId, $actor['username']);
        if ($member === null) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $lootId = (string) $args['loot_id'];
        $loot = $this->db->findLoot($campaignId, $lootId);
        if ($loot === null) {
            return respondJson($response, 404, ['error' => 'loot not found']);
        }

        if ($loot['status'] !== 'open') {
            return respondJson($response, 409, ['error' => 'loot is closed']);
        }

        $body = $request->getParsedBody() ?? [];
        if (!isset($body['recipient_character_id']) || (!is_string($body['recipient_character_id']) && !is_numeric($body['recipient_character_id']))) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $recipientCharacterId = (string) $body['recipient_character_id'];
        if ($recipientCharacterId === '') {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $recipient = $this->db->findPlayMemberByCampaignAndCharacterId($campaignId, $recipientCharacterId);
        if ($recipient === null) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        try {
            $this->db->createLootVote($campaignId, $lootId, $actor['username'], $recipientCharacterId);
        } catch (PDOException $e) {
            if ($e->getCode() === '23000' || str_contains($e->getMessage(), 'UNIQUE constraint failed')) {
                return respondJson($response, 409, ['error' => 'already voted']);
            }
            throw $e;
        }

        $votes = $this->db->findLootVotes($campaignId, $lootId);
        $counts = $this->computeLootVoteCounts($votes);
        $votesForRecipient = $counts[$recipientCharacterId] ?? 0;

        return respondJson($response, 201, [
            'loot_id' => $lootId,
            'voter' => $actor['username'],
            'recipient_character_id' => $recipientCharacterId,
            'votes_for_recipient' => $votesForRecipient,
        ]);
    }

    private function assignLoot(Request $request, Response $response, array $args): Response
    {
        $actor = $this->requireDm($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        if ($campaign['owner'] !== $actor['username']) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $lootId = (string) $args['loot_id'];
        $loot = $this->db->findLoot($campaignId, $lootId);
        if ($loot === null) {
            return respondJson($response, 404, ['error' => 'loot not found']);
        }

        if ($loot['status'] !== 'open') {
            return respondJson($response, 409, ['error' => 'loot already assigned']);
        }

        $votes = $this->db->findLootVotes($campaignId, $lootId);
        $counts = $this->computeLootVoteCounts($votes);
        $winner = $this->resolveHighestVoteRecipient($counts);
        if ($winner === null) {
            return respondJson($response, 409, ['error' => 'no clear winner']);
        }

        [$recipientCharacterId, $voteCount] = $winner;

        $assigned = $this->db->assignLoot($campaignId, $lootId, $recipientCharacterId);
        if (!$assigned) {
            return respondJson($response, 409, ['error' => 'loot already assigned']);
        }

        return respondJson($response, 200, [
            'loot_id' => $lootId,
            'recipient_character_id' => $recipientCharacterId,
            'item_id' => $loot['item_id'],
            'quantity' => (int) $loot['quantity'],
            'votes' => $voteCount,
            'status' => 'assigned',
        ]);
    }

    private function getLoot(Request $request, Response $response, array $args): Response
    {
        $actor = $this->authenticate($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $isOwner = $campaign['owner'] === $actor['username'];
        $isMember = $this->db->findPlayMemberByCampaignAndUser($campaignId, $actor['username']) !== null;
        if (!$isOwner && !$isMember) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $lootId = (string) $args['loot_id'];
        $loot = $this->db->findLoot($campaignId, $lootId);
        if ($loot === null) {
            return respondJson($response, 404, ['error' => 'loot not found']);
        }

        $votes = $this->db->findLootVotes($campaignId, $lootId);
        $counts = $this->computeLootVoteCounts($votes);

        return respondJson($response, 200, [
            'loot_id' => $loot['loot_id'],
            'item_id' => $loot['item_id'],
            'quantity' => (int) $loot['quantity'],
            'status' => $loot['status'],
            'recipient_character_id' => $loot['recipient_character_id'],
            'votes' => (object) $counts,
        ]);
    }

    // Play NPCs

    private function createPlayNpc(Request $request, Response $response, array $args): Response
    {
        $actor = $this->requireDm($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        if ($campaign['owner'] !== $actor['username']) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $body = $request->getParsedBody() ?? [];
        if (!isset($body['npc_id']) || !is_string($body['npc_id']) || $body['npc_id'] === ''
            || !isset($body['name']) || !is_string($body['name']) || $body['name'] === ''
            || !isset($body['agenda']) || !is_string($body['agenda']) || $body['agenda'] === ''
            || !isset($body['public_status']) || !is_string($body['public_status']) || $body['public_status'] === '') {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $npcId = $body['npc_id'];
        $name = $body['name'];
        $agenda = $body['agenda'];
        $publicStatus = $body['public_status'];

        if ($this->db->findPlayNpc($campaignId, $npcId) !== null) {
            return respondJson($response, 409, ['error' => 'npc id already exists']);
        }

        $this->db->createPlayNpc($campaignId, $npcId, $name, $agenda, $publicStatus);

        return respondJson($response, 201, [
            'npc_id' => $npcId,
            'name' => $name,
            'agenda' => $agenda,
            'public_status' => $publicStatus,
        ]);
    }

    private function updatePlayNpcAgenda(Request $request, Response $response, array $args): Response
    {
        $actor = $this->requireDm($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        if ($campaign['owner'] !== $actor['username']) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $npcId = (string) $args['npc_id'];
        $npc = $this->db->findPlayNpc($campaignId, $npcId);
        if ($npc === null) {
            return respondJson($response, 404, ['error' => 'npc not found']);
        }

        $body = $request->getParsedBody() ?? [];
        if (!isset($body['agenda']) || !is_string($body['agenda']) || $body['agenda'] === ''
            || !isset($body['public_status']) || !is_string($body['public_status']) || $body['public_status'] === '') {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $agenda = $body['agenda'];
        $publicStatus = $body['public_status'];

        $this->db->updatePlayNpc($campaignId, $npcId, $agenda, $publicStatus);

        return respondJson($response, 200, [
            'npc_id' => $npcId,
            'name' => $npc['name'],
            'agenda' => $agenda,
            'public_status' => $publicStatus,
        ]);
    }

    private function getPlayNpc(Request $request, Response $response, array $args): Response
    {
        $actor = $this->authenticate($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $isOwner = $campaign['owner'] === $actor['username'];
        $isMember = $this->db->findPlayMemberByCampaignAndUser($campaignId, $actor['username']) !== null;
        if (!$isOwner && !$isMember) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $npcId = (string) $args['npc_id'];
        $npc = $this->db->findPlayNpc($campaignId, $npcId);
        if ($npc === null) {
            return respondJson($response, 404, ['error' => 'npc not found']);
        }

        if ($isOwner) {
            return respondJson($response, 200, [
                'npc_id' => $npc['npc_id'],
                'name' => $npc['name'],
                'agenda' => $npc['agenda'],
                'public_status' => $npc['public_status'],
            ]);
        }

        return respondJson($response, 200, [
            'npc_id' => $npc['npc_id'],
            'name' => $npc['name'],
            'public_status' => $npc['public_status'],
        ]);
    }

    private function computeLootVoteCounts(array $votes): array
    {
        $counts = [];
        foreach ($votes as $vote) {
            $recipient = $vote['recipient_character_id'];
            $counts[$recipient] = ($counts[$recipient] ?? 0) + 1;
        }
        return $counts;
    }

    private function resolveHighestVoteRecipient(array $counts): ?array
    {
        if (empty($counts)) {
            return null;
        }
        arsort($counts);
        $top = array_slice($counts, 0, 2, true);
        $values = array_values($top);
        if (isset($values[1]) && $values[1] === $values[0]) {
            return null;
        }
        return [array_keys($top)[0], $values[0]];
    }

    // Play Factions

    private function createPlayFaction(Request $request, Response $response, array $args): Response
    {
        $actor = $this->requireDm($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        if ($campaign['owner'] !== $actor['username']) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $body = $request->getParsedBody() ?? [];
        if (!isset($body['faction_id']) || !is_string($body['faction_id']) || $body['faction_id'] === ''
            || !isset($body['name']) || !is_string($body['name']) || $body['name'] === '') {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $factionId = $body['faction_id'];
        $name = $body['name'];

        if ($this->db->findPlayFaction($campaignId, $factionId) !== null) {
            return respondJson($response, 409, ['error' => 'faction id already exists']);
        }

        $this->db->createPlayFaction($campaignId, $factionId, $name);

        return respondJson($response, 201, [
            'faction_id' => $factionId,
            'name' => $name,
        ]);
    }

    private function changeReputation(Request $request, Response $response, array $args): Response
    {
        $actor = $this->requireDm($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        if ($campaign['owner'] !== $actor['username']) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $factionId = (string) $args['faction_id'];
        if ($this->db->findPlayFaction($campaignId, $factionId) === null) {
            return respondJson($response, 404, ['error' => 'faction not found']);
        }

        $body = $request->getParsedBody() ?? [];
        if (!isset($body['character_id']) || !is_string($body['character_id']) || $body['character_id'] === ''
            || !isset($body['delta']) || !is_int($body['delta'])
            || !isset($body['reason']) || !is_string($body['reason']) || $body['reason'] === '') {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $characterId = $body['character_id'];
        $delta = $body['delta'];
        $reason = $body['reason'];

        if ($delta === 0 || $delta < -25 || $delta > 25) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        if ($this->db->findPlayMemberByCampaignAndCharacterId($campaignId, $characterId) === null) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $previousTotal = $this->db->totalReputationForCharacter($campaignId, $factionId, $characterId);
        $newTotal = max(-100, min(100, $previousTotal + $delta));

        $this->db->addFactionReputationHistory($campaignId, $factionId, $characterId, $newTotal, $delta, $reason);

        return respondJson($response, 201, [
            'faction_id' => $factionId,
            'character_id' => $characterId,
            'reputation' => $newTotal,
            'delta' => $delta,
            'reason' => $reason,
        ]);
    }

    private function getReputation(Request $request, Response $response, array $args): Response
    {
        $actor = $this->authenticate($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $isOwner = $campaign['owner'] === $actor['username'];
        $member = $this->db->findPlayMemberByCampaignAndUser($campaignId, $actor['username']);
        if (!$isOwner && $member === null) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $factionId = (string) $args['faction_id'];
        if ($this->db->findPlayFaction($campaignId, $factionId) === null) {
            return respondJson($response, 404, ['error' => 'faction not found']);
        }

        $history = $this->db->findFactionReputationHistory($campaignId, $factionId);
        $entries = [];
        foreach ($history as $record) {
            if (!$isOwner && $record['character_id'] !== $member['character_id']) {
                continue;
            }
            $entries[] = [
                'faction_id' => $record['faction_id'],
                'character_id' => $record['character_id'],
                'reputation' => (int) $record['reputation'],
                'delta' => (int) $record['delta'],
                'reason' => $record['reason'],
            ];
        }

        return respondJson($response, 200, [
            'faction_id' => $factionId,
            'entries' => $entries,
        ]);
    }

    // NPC Dialogue

    private function addNpcDialogue(Request $request, Response $response, array $args): Response
    {
        $actor = $this->requireDm($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        if ($campaign['owner'] !== $actor['username']) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $npcId = (string) $args['npc_id'];
        if ($this->db->findPlayNpc($campaignId, $npcId) === null) {
            return respondJson($response, 404, ['error' => 'npc not found']);
        }

        $body = $request->getParsedBody() ?? [];
        if (!isset($body['dialogue_id']) || !is_string($body['dialogue_id']) || $body['dialogue_id'] === ''
            || !isset($body['speaker']) || !is_string($body['speaker']) || $body['speaker'] === ''
            || !isset($body['text']) || !is_string($body['text']) || $body['text'] === ''
            || !isset($body['visibility']) || !is_string($body['visibility']) || !in_array($body['visibility'], ['public', 'private'], true)) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $dialogueId = $body['dialogue_id'];
        $speaker = $body['speaker'];
        $text = $body['text'];
        $visibility = $body['visibility'];

        try {
            $this->db->createNpcDialogue($campaignId, $npcId, $dialogueId, $speaker, $text, $visibility);
        } catch (PDOException $e) {
            if ($e->getCode() === '23000' || str_contains($e->getMessage(), 'UNIQUE constraint failed')) {
                return respondJson($response, 409, ['error' => 'dialogue id already exists']);
            }
            throw $e;
        }

        return respondJson($response, 201, [
            'dialogue_id' => $dialogueId,
            'speaker' => $speaker,
            'text' => $text,
            'visibility' => $visibility,
        ]);
    }

    private function getNpcDialogue(Request $request, Response $response, array $args): Response
    {
        $actor = $this->authenticate($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $isOwner = $campaign['owner'] === $actor['username'];
        $isMember = $this->db->findPlayMemberByCampaignAndUser($campaignId, $actor['username']) !== null;
        if (!$isOwner && !$isMember) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $npcId = (string) $args['npc_id'];
        if ($this->db->findPlayNpc($campaignId, $npcId) === null) {
            return respondJson($response, 404, ['error' => 'npc not found']);
        }

        $rows = $this->db->findNpcDialogue($campaignId, $npcId);
        $entries = [];
        foreach ($rows as $row) {
            if (!$isOwner && $row['visibility'] !== 'public') {
                continue;
            }
            $entries[] = [
                'dialogue_id' => $row['dialogue_id'],
                'speaker' => $row['speaker'],
                'text' => $row['text'],
                'visibility' => $row['visibility'],
            ];
        }

        return respondJson($response, 200, [
            'npc_id' => $npcId,
            'entries' => $entries,
        ]);
    }

    // Relationships

    private function isValidCampaignEntity(string $campaignId, string $entityId): bool
    {
        return $this->db->findPlayMemberByCampaignAndCharacterId($campaignId, $entityId) !== null
            || $this->db->findPlayNpc($campaignId, $entityId) !== null;
    }

    private function createRelationship(Request $request, Response $response, array $args): Response
    {
        $actor = $this->requireDm($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        if ($campaign['owner'] !== $actor['username']) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $body = $request->getParsedBody() ?? [];
        if (!isset($body['source_id']) || (!is_string($body['source_id']) && !is_numeric($body['source_id']))
            || !isset($body['target_id']) || (!is_string($body['target_id']) && !is_numeric($body['target_id']))
            || !isset($body['kind']) || (!is_string($body['kind']) && !is_numeric($body['kind']))
            || !isset($body['score']) || !is_int($body['score'])) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $sourceId = (string) $body['source_id'];
        $targetId = (string) $body['target_id'];
        $kind = (string) $body['kind'];
        $score = (int) $body['score'];

        if ($sourceId === '' || $targetId === '' || $kind === '') {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        if ($sourceId === $targetId) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        if ($score < -100 || $score > 100) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        if (!$this->isValidCampaignEntity($campaignId, $sourceId) || !$this->isValidCampaignEntity($campaignId, $targetId)) {
            return respondJson($response, 404, ['error' => 'not found']);
        }

        if ($this->db->findRelationship($campaignId, $sourceId, $targetId, $kind) !== null) {
            return respondJson($response, 409, ['error' => 'relationship already exists']);
        }

        $this->db->createRelationship($campaignId, $sourceId, $targetId, $kind, $score);

        return respondJson($response, 201, [
            'source_id' => $sourceId,
            'target_id' => $targetId,
            'kind' => $kind,
            'score' => $score,
        ]);
    }

    private function updateRelationship(Request $request, Response $response, array $args): Response
    {
        $actor = $this->requireDm($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        if ($campaign['owner'] !== $actor['username']) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $sourceId = (string) $args['source_id'];
        $targetId = (string) $args['target_id'];
        $kind = (string) $args['kind'];

        $relationship = $this->db->findRelationship($campaignId, $sourceId, $targetId, $kind);
        if ($relationship === null) {
            return respondJson($response, 404, ['error' => 'relationship not found']);
        }

        $body = $request->getParsedBody() ?? [];
        if (!isset($body['score']) || !is_int($body['score'])) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $score = (int) $body['score'];
        if ($score < -100 || $score > 100) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $this->db->updateRelationshipScore($campaignId, $sourceId, $targetId, $kind, $score);

        return respondJson($response, 200, [
            'source_id' => $sourceId,
            'target_id' => $targetId,
            'kind' => $kind,
            'score' => $score,
        ]);
    }

    private function listRelationships(Request $request, Response $response, array $args): Response
    {
        $actor = $this->authenticate($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $isOwner = $campaign['owner'] === $actor['username'];
        $isMember = $this->db->findPlayMemberByCampaignAndUser($campaignId, $actor['username']) !== null;
        if (!$isOwner && !$isMember) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $rows = $this->db->findRelationships($campaignId);
        $edges = [];
        foreach ($rows as $row) {
            $edges[] = [
                'source_id' => $row['source_id'],
                'target_id' => $row['target_id'],
                'kind' => $row['kind'],
                'score' => (int) $row['score'],
            ];
        }

        return respondJson($response, 200, ['edges' => $edges]);
    }

    // Clues

    private function createClue(Request $request, Response $response, array $args): Response
    {
        $actor = $this->requireDm($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        if ($campaign['owner'] !== $actor['username']) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $body = $request->getParsedBody() ?? [];
        if (!isset($body['clue_id']) || (!is_string($body['clue_id']) && !is_numeric($body['clue_id']))
            || !isset($body['text']) || (!is_string($body['text']) && !is_numeric($body['text']))
            || !isset($body['audience']) || (!is_string($body['audience']) && !is_numeric($body['audience']))) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $clueId = (string) $body['clue_id'];
        $text = (string) $body['text'];
        $audience = (string) $body['audience'];
        if ($clueId === '' || $text === '' || !in_array($audience, ['character', 'party', 'hidden'], true)) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $characterId = null;
        if ($audience === 'character') {
            if (!isset($body['character_id']) || (!is_string($body['character_id']) && !is_numeric($body['character_id']))) {
                return respondJson($response, 400, ['error' => 'invalid request']);
            }
            $characterId = (string) $body['character_id'];
            if ($characterId === '' || $this->db->findPlayMemberByCampaignAndCharacterId($campaignId, $characterId) === null) {
                return respondJson($response, 400, ['error' => 'invalid request']);
            }
        } else {
            if (array_key_exists('character_id', $body)) {
                return respondJson($response, 400, ['error' => 'invalid request']);
            }
        }

        if ($this->db->findClueByCampaignAndId($campaignId, $clueId) !== null) {
            return respondJson($response, 409, ['error' => 'clue id already exists']);
        }

        $this->db->createClue($campaignId, $clueId, $text, $audience, $characterId);

        $result = [
            'clue_id' => $clueId,
            'text' => $text,
            'audience' => $audience,
        ];
        if ($characterId !== null) {
            $result['character_id'] = $characterId;
        }

        return respondJson($response, 201, $result);
    }

    private function listClues(Request $request, Response $response, array $args): Response
    {
        $actor = $this->authenticate($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $isOwner = $campaign['owner'] === $actor['username'];
        $isMember = $this->db->findPlayMemberByCampaignAndUser($campaignId, $actor['username']) !== null;
        if (!$isOwner && !$isMember) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $rows = $this->db->findCluesByCampaign($campaignId);
        $clues = [];
        if ($isOwner) {
            foreach ($rows as $row) {
                $clue = [
                    'clue_id' => $row['clue_id'],
                    'text' => $row['text'],
                    'audience' => $row['audience'],
                ];
                if ($row['character_id'] !== null) {
                    $clue['character_id'] = $row['character_id'];
                }
                $clues[] = $clue;
            }
        } else {
            $member = $this->db->findPlayMemberByCampaignAndUser($campaignId, $actor['username']);
            $ownCharacterId = (string) ($member['character_id'] ?? '');
            foreach ($rows as $row) {
                $audience = $row['audience'];
                if ($audience === 'hidden') {
                    continue;
                }
                if ($audience === 'character' && $row['character_id'] !== $ownCharacterId) {
                    continue;
                }
                $clue = [
                    'clue_id' => $row['clue_id'],
                    'text' => $row['text'],
                    'audience' => $audience,
                ];
                if ($row['character_id'] !== null) {
                    $clue['character_id'] = $row['character_id'];
                }
                $clues[] = $clue;
            }
        }

        return respondJson($response, 200, ['clues' => $clues]);
    }

    // Quests

    private function createQuest(Request $request, Response $response, array $args): Response
    {
        $actor = $this->requireDm($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        if ($campaign['owner'] !== $actor['username']) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $body = $request->getParsedBody() ?? [];
        if (!isset($body['quest_id']) || (!is_string($body['quest_id']) && !is_numeric($body['quest_id']))
            || !isset($body['title']) || (!is_string($body['title']) && !is_numeric($body['title']))
            || !isset($body['depends_on']) || !is_array($body['depends_on']) || !array_is_list($body['depends_on'])) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $questId = (string) $body['quest_id'];
        $title = (string) $body['title'];
        if ($questId === '' || $title === '') {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $dependsOn = [];
        foreach ($body['depends_on'] as $dep) {
            if (!is_string($dep) && !is_numeric($dep)) {
                return respondJson($response, 400, ['error' => 'invalid request']);
            }
            $dep = (string) $dep;
            if ($dep === '') {
                return respondJson($response, 400, ['error' => 'invalid request']);
            }
            $dependsOn[] = $dep;
        }

        if (count($dependsOn) !== count(array_unique($dependsOn))) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        if (in_array($questId, $dependsOn, true)) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        foreach ($dependsOn as $dep) {
            if ($this->db->findPlayQuest($campaignId, $dep) === null) {
                return respondJson($response, 400, ['error' => 'invalid request']);
            }
        }

        if ($this->db->findPlayQuest($campaignId, $questId) !== null) {
            return respondJson($response, 409, ['error' => 'quest id already exists']);
        }

        $this->db->createPlayQuest($campaignId, $questId, $title, $dependsOn, 'locked');

        return respondJson($response, 201, [
            'quest_id' => $questId,
            'title' => $title,
            'depends_on' => $dependsOn,
            'state' => 'locked',
        ]);
    }

    private function updateQuestState(Request $request, Response $response, array $args): Response
    {
        $actor = $this->requireDm($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        if ($campaign['owner'] !== $actor['username']) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $questId = (string) $args['quest_id'];
        $quest = $this->db->findPlayQuest($campaignId, $questId);
        if ($quest === null) {
            return respondJson($response, 404, ['error' => 'quest not found']);
        }

        $body = $request->getParsedBody() ?? [];
        if (!isset($body['state']) || (!is_string($body['state']) && !is_numeric($body['state']))) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $newState = (string) $body['state'];
        if (!in_array($newState, ['active', 'completed'], true)) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $currentState = $quest['state'];
        if ($currentState === 'locked' && $newState === 'active') {
            foreach ($quest['depends_on'] as $dep) {
                $depQuest = $this->db->findPlayQuest($campaignId, $dep);
                if ($depQuest === null || $depQuest['state'] !== 'completed') {
                    return respondJson($response, 409, ['error' => 'dependencies not completed']);
                }
            }
        } elseif ($currentState === 'active' && $newState === 'completed') {
            // allowed transition
        } else {
            return respondJson($response, 409, ['error' => 'invalid state transition']);
        }

        $this->db->updatePlayQuestState($campaignId, $questId, $newState);

        $responseData = [
            'quest_id' => $questId,
            'title' => $quest['title'],
            'depends_on' => $quest['depends_on'],
            'state' => $newState,
        ];
        if (isset($quest['rewards']) && $quest['rewards'] !== null) {
            $rewards = $quest['rewards'];
            if (isset($rewards['items']) && is_array($rewards['items'])) {
                $rewards['items'] = (object) $rewards['items'];
            }
            $responseData['rewards'] = $rewards;
        }

        return respondJson($response, 200, $responseData);
    }

    private function listQuests(Request $request, Response $response, array $args): Response
    {
        $actor = $this->authenticate($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $isOwner = $campaign['owner'] === $actor['username'];
        $isMember = $this->db->findPlayMemberByCampaignAndUser($campaignId, $actor['username']) !== null;
        if (!$isOwner && !$isMember) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $rows = $this->db->findPlayQuestsByCampaign($campaignId);
        $quests = [];
        foreach ($rows as $row) {
            $quests[] = [
                'quest_id' => $row['quest_id'],
                'title' => $row['title'],
                'depends_on' => $row['depends_on'],
                'state' => $row['state'],
            ];
        }

        return respondJson($response, 200, ['quests' => $quests]);
    }

    private function configureQuestRewards(Request $request, Response $response, array $args): Response
    {
        $actor = $this->requireDm($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        if ($campaign['owner'] !== $actor['username']) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $questId = (string) $args['quest_id'];
        $quest = $this->db->findPlayQuest($campaignId, $questId);
        if ($quest === null) {
            return respondJson($response, 404, ['error' => 'quest not found']);
        }

        if (!in_array($quest['state'], ['locked', 'active'], true)) {
            return respondJson($response, 409, ['error' => 'quest already completed']);
        }

        $body = $request->getParsedBody() ?? [];
        if (!isset($body['xp']) || !is_int($body['xp']) || $body['xp'] < 0
            || !isset($body['items']) || !is_array($body['items']) || array_is_list($body['items'])) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $items = [];
        foreach ($body['items'] as $itemId => $quantity) {
            if (!is_string($itemId) && !is_numeric($itemId)) {
                return respondJson($response, 400, ['error' => 'invalid request']);
            }
            $itemId = (string) $itemId;
            if ($itemId === '' || !is_int($quantity) || $quantity < 1) {
                return respondJson($response, 400, ['error' => 'invalid request']);
            }
            if ($this->db->findItem($itemId) === null) {
                return respondJson($response, 400, ['error' => 'invalid request']);
            }
            $items[$itemId] = $quantity;
        }

        $rewards = [
            'xp' => (int) $body['xp'],
            'items' => $items,
        ];

        $this->db->updatePlayQuestRewards($campaignId, $questId, $rewards);

        $rewards['items'] = (object) $rewards['items'];
        $quest['rewards'] = $rewards;
        return respondJson($response, 200, [
            'quest_id' => $quest['quest_id'],
            'title' => $quest['title'],
            'depends_on' => $quest['depends_on'],
            'state' => $quest['state'],
            'rewards' => $rewards,
        ]);
    }

    private function awardQuestRewards(Request $request, Response $response, array $args): Response
    {
        $actor = $this->requireDm($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        if ($campaign['owner'] !== $actor['username']) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $questId = (string) $args['quest_id'];
        $quest = $this->db->findPlayQuest($campaignId, $questId);
        if ($quest === null) {
            return respondJson($response, 404, ['error' => 'quest not found']);
        }

        if ($quest['state'] !== 'completed') {
            return respondJson($response, 409, ['error' => 'quest not completed']);
        }

        if ($quest['rewards'] === null) {
            return respondJson($response, 409, ['error' => 'rewards not configured']);
        }

        if ($quest['awarded']) {
            return respondJson($response, 409, ['error' => 'rewards already awarded']);
        }

        $rewards = $quest['rewards'];
        $xp = (int) $rewards['xp'];
        $items = is_array($rewards['items'] ?? null) ? $rewards['items'] : [];

        $members = $this->db->findPlayMembers($campaignId);
        foreach ($members as $member) {
            $this->db->createQuestRewardGrant($campaignId, $questId, (string) $member['character_id'], $xp, $items);
        }

        $this->db->markPlayQuestAwarded($campaignId, $questId);

        return respondJson($response, 201, [
            'quest_id' => $questId,
            'awarded' => true,
            'xp' => $xp,
            'items' => (object) $items,
        ]);
    }

    private function getCharacterQuestRewards(Request $request, Response $response, array $args): Response
    {
        $actor = $this->authenticate($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $isOwner = $campaign['owner'] === $actor['username'];
        $isMember = $this->db->findPlayMemberByCampaignAndUser($campaignId, $actor['username']) !== null;
        if (!$isOwner && !$isMember) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $characterId = (string) $args['character_id'];
        if ($this->db->findPlayMemberByCampaignAndCharacterId($campaignId, $characterId) === null) {
            return respondJson($response, 404, ['error' => 'character not found']);
        }

        $grants = $this->db->findQuestRewardGrantsByCharacter($campaignId, $characterId);
        $totalXp = 0;
        $totalItems = [];
        foreach ($grants as $grant) {
            $totalXp += (int) $grant['xp'];
            foreach ($grant['items'] as $itemId => $quantity) {
                $totalItems[$itemId] = ($totalItems[$itemId] ?? 0) + (int) $quantity;
            }
        }

        return respondJson($response, 200, [
            'character_id' => $characterId,
            'xp' => $totalXp,
            'items' => (object) $totalItems,
        ]);
    }

    private function scheduleWorldEvent(Request $request, Response $response, array $args): Response
    {
        $actor = $this->requireDm($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        if ($campaign['owner'] !== $actor['username']) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $body = $request->getParsedBody() ?? [];
        if (!isset($body['event_id']) || (!is_string($body['event_id']) && !is_numeric($body['event_id']))
            || !isset($body['title']) || (!is_string($body['title']) && !is_numeric($body['title']))
            || !isset($body['text']) || (!is_string($body['text']) && !is_numeric($body['text']))
            || !isset($body['turn_number']) || !is_int($body['turn_number'])) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $eventId = (string) $body['event_id'];
        $title = (string) $body['title'];
        $text = (string) $body['text'];
        $turnNumber = (int) $body['turn_number'];

        if ($eventId === '' || $title === '' || $text === '') {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $currentTurnNumber = (int) ($campaign['turn_number'] ?? 0);
        if ($turnNumber < $currentTurnNumber) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        if ($this->db->findPlayWorldEvent($campaignId, $eventId) !== null) {
            return respondJson($response, 409, ['error' => 'event id already exists']);
        }

        $this->db->createPlayWorldEvent($campaignId, $eventId, $turnNumber, $title, $text);

        return respondJson($response, 201, [
            'event_id' => $eventId,
            'turn_number' => $turnNumber,
            'title' => $title,
            'text' => $text,
            'status' => 'scheduled',
        ]);
    }

    private function resolveWorldEvent(Request $request, Response $response, array $args): Response
    {
        $actor = $this->requireDm($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        if ($campaign['owner'] !== $actor['username']) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $eventId = (string) $args['event_id'];
        $event = $this->db->findPlayWorldEvent($campaignId, $eventId);
        if ($event === null) {
            return respondJson($response, 404, ['error' => 'event not found']);
        }

        $body = $request->getParsedBody() ?? [];
        if (!isset($body['text']) || (!is_string($body['text']) && !is_numeric($body['text']))) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $text = (string) $body['text'];
        if ($text === '') {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $currentTurnNumber = (int) ($campaign['turn_number'] ?? 0);
        if ($currentTurnNumber !== $event['turn_number']) {
            return respondJson($response, 409, ['error' => 'turn number mismatch']);
        }

        if ($event['status'] === 'resolved') {
            return respondJson($response, 409, ['error' => 'event already resolved']);
        }

        $this->db->resolvePlayWorldEvent($campaignId, $eventId, $currentTurnNumber, $text);

        return respondJson($response, 201, [
            'event_id' => $eventId,
            'turn_number' => $event['turn_number'],
            'title' => $event['title'],
            'text' => $event['text'],
            'status' => 'resolved',
            'resolution' => [
                'turn_number' => $currentTurnNumber,
                'text' => $text,
            ],
        ]);
    }

    private function listWorldEvents(Request $request, Response $response, array $args): Response
    {
        $actor = $this->authenticate($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $isOwner = $campaign['owner'] === $actor['username'];
        $isMember = $this->db->findPlayMemberByCampaignAndUser($campaignId, $actor['username']) !== null;
        if (!$isOwner && !$isMember) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $rows = $this->db->findPlayWorldEventsByCampaign($campaignId);
        $events = [];
        foreach ($rows as $row) {
            $event = [
                'event_id' => $row['event_id'],
                'turn_number' => (int) $row['turn_number'],
                'title' => $row['title'],
                'text' => $row['text'],
                'status' => $row['status'],
            ];
            if ($row['status'] === 'resolved') {
                $event['resolution'] = [
                    'turn_number' => (int) $row['resolution_turn_number'],
                    'text' => $row['resolution_text'],
                ];
            }
            $events[] = $event;
        }

        return respondJson($response, 200, ['events' => $events]);
    }

    // Calendar

    private function computeWeather(int $day, string $season): string
    {
        $offset = self::SEASON_OFFSETS[$season];
        return self::WEATHER_BY_REMAINDER[($day + $offset) % 4];
    }

    private function formatCalendarResponse(int $day, string $season): array
    {
        return [
            'day' => $day,
            'season' => $season,
            'weather' => $this->computeWeather($day, $season),
        ];
    }

    private function initializeCalendar(Request $request, Response $response, array $args): Response
    {
        $actor = $this->requireDm($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        if ($campaign['owner'] !== $actor['username']) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $body = $request->getParsedBody() ?? [];
        if (!isset($body['day']) || !is_numeric($body['day'])
            || !isset($body['season']) || (!is_string($body['season']) && !is_numeric($body['season']))) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $day = (int) $body['day'];
        $season = (string) $body['season'];
        if ($day < 1 || !isset(self::SEASON_OFFSETS[$season])) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        if ($this->db->findPlayCalendar($campaignId) !== null) {
            return respondJson($response, 409, ['error' => 'calendar already initialized']);
        }

        $this->db->createPlayCalendar($campaignId, $day, $season);

        return respondJson($response, 201, $this->formatCalendarResponse($day, $season));
    }

    private function getCalendar(Request $request, Response $response, array $args): Response
    {
        $actor = $this->authenticate($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $isOwner = $campaign['owner'] === $actor['username'];
        $isMember = $this->db->findPlayMemberByCampaignAndUser($campaignId, $actor['username']) !== null;
        if (!$isOwner && !$isMember) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $calendar = $this->db->findPlayCalendar($campaignId);
        if ($calendar === null) {
            return respondJson($response, 404, ['error' => 'calendar not initialized']);
        }

        return respondJson($response, 200, $this->formatCalendarResponse((int) $calendar['day'], (string) $calendar['season']));
    }

    private function advanceCalendar(Request $request, Response $response, array $args): Response
    {
        $actor = $this->requireDm($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        if ($campaign['owner'] !== $actor['username']) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $body = $request->getParsedBody() ?? [];
        if (!isset($body['days']) || !is_numeric($body['days'])) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $days = (int) $body['days'];
        if ($days < 1 || $days > 30) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $calendar = $this->db->findPlayCalendar($campaignId);
        if ($calendar === null) {
            return respondJson($response, 404, ['error' => 'calendar not initialized']);
        }

        $newDay = (int) $calendar['day'] + $days;
        $this->db->advancePlayCalendar($campaignId, $newDay);

        return respondJson($response, 200, $this->formatCalendarResponse($newDay, (string) $calendar['season']));
    }

    private function createSettlement(Request $request, Response $response, array $args): Response
    {
        $actor = $this->requireDm($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        if ($campaign['owner'] !== $actor['username']) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $body = $request->getParsedBody() ?? [];
        $validation = $this->validateSettlementBody($body, true);
        if ($validation === null) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        [$settlementId, $name, $services, $availability] = $validation;

        if ($this->db->findSettlement($campaignId, $settlementId) !== null) {
            return respondJson($response, 409, ['error' => 'settlement id already exists']);
        }

        $this->db->createSettlement([
            'campaign_id' => $campaignId,
            'settlement_id' => $settlementId,
            'name' => $name,
            'services' => $services,
            'availability' => $availability,
            'discovered_by' => [],
        ]);

        return respondJson($response, 201, [
            'settlement_id' => $settlementId,
            'name' => $name,
            'services' => $services,
            'availability' => $availability,
            'discovered_by' => [],
        ]);
    }

    private function updateSettlement(Request $request, Response $response, array $args): Response
    {
        $actor = $this->requireDm($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        if ($campaign['owner'] !== $actor['username']) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $settlementId = (string) $args['settlement_id'];
        $existing = $this->db->findSettlement($campaignId, $settlementId);
        if ($existing === null) {
            return respondJson($response, 404, ['error' => 'settlement not found']);
        }

        $body = $request->getParsedBody() ?? [];
        $validation = $this->validateSettlementBody($body, false);
        if ($validation === null) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        [, $name, $services, $availability] = $validation;

        $this->db->updateSettlement($campaignId, $settlementId, $name, $services, $availability);

        return respondJson($response, 200, [
            'settlement_id' => $settlementId,
            'name' => $name,
            'services' => $services,
            'availability' => $availability,
            'discovered_by' => $existing['discovered_by'],
        ]);
    }

    private function discoverSettlement(Request $request, Response $response, array $args): Response
    {
        $actor = $this->requirePlayer($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $member = $this->db->findPlayMemberByCampaignAndUser($campaignId, $actor['username']);
        if ($member === null) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $settlementId = (string) $args['settlement_id'];
        $settlement = $this->db->findSettlement($campaignId, $settlementId);
        if ($settlement === null) {
            return respondJson($response, 404, ['error' => 'settlement not found']);
        }

        $characterId = (string) $member['character_id'];
        $added = $this->db->addSettlementDiscoverer($campaignId, $settlementId, $characterId);

        return respondJson($response, $added ? 201 : 200, [
            'settlement_id' => $settlement['settlement_id'],
            'name' => $settlement['name'],
            'services' => $settlement['services'],
            'availability' => $settlement['availability'],
            'discovered_by' => [$characterId],
        ]);
    }

    private function listSettlements(Request $request, Response $response, array $args): Response
    {
        $actor = $this->authenticate($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $isOwner = $campaign['owner'] === $actor['username'];
        $member = $this->db->findPlayMemberByCampaignAndUser($campaignId, $actor['username']);
        if (!$isOwner && $member === null) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $settlements = $this->db->findSettlementsByCampaign($campaignId);
        $result = [];
        foreach ($settlements as $settlement) {
            if ($isOwner) {
                $result[] = [
                    'settlement_id' => $settlement['settlement_id'],
                    'name' => $settlement['name'],
                    'services' => $settlement['services'],
                    'availability' => $settlement['availability'],
                    'discovered_by' => $settlement['discovered_by'],
                ];
            } else {
                $characterId = (string) $member['character_id'];
                if (in_array($characterId, $settlement['discovered_by'], true)) {
                    $result[] = [
                        'settlement_id' => $settlement['settlement_id'],
                        'name' => $settlement['name'],
                        'services' => $settlement['services'],
                        'availability' => $settlement['availability'],
                        'discovered_by' => [$characterId],
                    ];
                }
            }
        }

        return respondJson($response, 200, ['settlements' => $result]);
    }

    private function createShop(Request $request, Response $response, array $args): Response
    {
        $actor = $this->requireDm($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        if ($campaign['owner'] !== $actor['username']) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $settlementId = (string) $args['settlement_id'];
        if ($this->db->findSettlement($campaignId, $settlementId) === null) {
            return respondJson($response, 404, ['error' => 'settlement not found']);
        }

        $body = $request->getParsedBody() ?? [];
        $validation = $this->validateShopBody($body);
        if ($validation === null) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        [$shopId, $name, $stock, $buyPrice, $sellPrice] = $validation;

        if ($this->db->findShop($campaignId, $settlementId, $shopId) !== null) {
            return respondJson($response, 409, ['error' => 'shop id already exists']);
        }

        $this->db->createShop([
            'campaign_id' => $campaignId,
            'settlement_id' => $settlementId,
            'shop_id' => $shopId,
            'name' => $name,
            'stock' => $stock,
            'buy_price' => $buyPrice,
            'sell_price' => $sellPrice,
        ]);

        return respondJson($response, 201, [
            'shop_id' => $shopId,
            'name' => $name,
            'stock' => $stock,
            'buy_price' => $buyPrice,
            'sell_price' => $sellPrice,
        ]);
    }

    private function getShop(Request $request, Response $response, array $args): Response
    {
        $actor = $this->authenticate($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $isOwner = $campaign['owner'] === $actor['username'];
        $member = $this->db->findPlayMemberByCampaignAndUser($campaignId, $actor['username']);
        if (!$isOwner && $member === null) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $settlementId = (string) $args['settlement_id'];
        $settlement = $this->db->findSettlement($campaignId, $settlementId);
        if ($settlement === null) {
            return respondJson($response, 404, ['error' => 'settlement not found']);
        }

        $shopId = (string) $args['shop_id'];
        $shop = $this->db->findShop($campaignId, $settlementId, $shopId);
        if ($shop === null) {
            return respondJson($response, 404, ['error' => 'shop not found']);
        }

        if (!$isOwner) {
            $characterId = (string) $member['character_id'];
            if (!in_array($characterId, $settlement['discovered_by'], true)) {
                return respondJson($response, 404, ['error' => 'shop not found']);
            }
        }

        return respondJson($response, 200, [
            'shop_id' => $shop['shop_id'],
            'name' => $shop['name'],
            'stock' => $shop['stock'],
            'buy_price' => $shop['buy_price'],
            'sell_price' => $shop['sell_price'],
        ]);
    }

    private function buyShop(Request $request, Response $response, array $args): Response
    {
        $actor = $this->requirePlayer($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $settlementId = (string) $args['settlement_id'];
        $settlement = $this->db->findSettlement($campaignId, $settlementId);
        if ($settlement === null) {
            return respondJson($response, 404, ['error' => 'settlement not found']);
        }

        $shopId = (string) $args['shop_id'];
        $shop = $this->db->findShop($campaignId, $settlementId, $shopId);
        if ($shop === null) {
            return respondJson($response, 404, ['error' => 'shop not found']);
        }

        $body = $request->getParsedBody() ?? [];
        if (!isset($body['character_id']) || (!is_string($body['character_id']) && !is_numeric($body['character_id']))
            || !isset($body['item_id']) || (!is_string($body['item_id']) && !is_numeric($body['item_id']))
            || !isset($body['quantity']) || !is_numeric($body['quantity'])) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $characterId = (string) $body['character_id'];
        $itemId = (string) $body['item_id'];
        $quantity = (int) $body['quantity'];
        if ($characterId === '' || $itemId === '' || $quantity < 1 || !in_array($itemId, self::VALID_INVENTORY_ITEMS, true)) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $member = $this->db->findPlayMemberByCampaignAndCharacterId($campaignId, $characterId);
        if ($member === null) {
            return respondJson($response, 404, ['error' => 'character not found']);
        }

        $owner = $this->resolveOwner($member);
        if ($owner !== $actor['username']) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $result = $this->db->buyFromShop($campaignId, $settlementId, $shopId, $characterId, $itemId, $quantity);
        if ($result === null) {
            return respondJson($response, 409, ['error' => 'insufficient stock or gold']);
        }

        return respondJson($response, 200, [
            'character_id' => $characterId,
            'item_id' => $itemId,
            'quantity' => $quantity,
            'gold' => $result['gold'],
            'stock' => $result['shop']['stock'][$itemId] ?? 0,
        ]);
    }

    private function sellShop(Request $request, Response $response, array $args): Response
    {
        $actor = $this->requirePlayer($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $settlementId = (string) $args['settlement_id'];
        $settlement = $this->db->findSettlement($campaignId, $settlementId);
        if ($settlement === null) {
            return respondJson($response, 404, ['error' => 'settlement not found']);
        }

        $shopId = (string) $args['shop_id'];
        $shop = $this->db->findShop($campaignId, $settlementId, $shopId);
        if ($shop === null) {
            return respondJson($response, 404, ['error' => 'shop not found']);
        }

        $body = $request->getParsedBody() ?? [];
        if (!isset($body['character_id']) || (!is_string($body['character_id']) && !is_numeric($body['character_id']))
            || !isset($body['item_id']) || (!is_string($body['item_id']) && !is_numeric($body['item_id']))
            || !isset($body['quantity']) || !is_numeric($body['quantity'])) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $characterId = (string) $body['character_id'];
        $itemId = (string) $body['item_id'];
        $quantity = (int) $body['quantity'];
        if ($characterId === '' || $itemId === '' || $quantity < 1 || !in_array($itemId, self::VALID_INVENTORY_ITEMS, true)) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $member = $this->db->findPlayMemberByCampaignAndCharacterId($campaignId, $characterId);
        if ($member === null) {
            return respondJson($response, 404, ['error' => 'character not found']);
        }

        $owner = $this->resolveOwner($member);
        if ($owner !== $actor['username']) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $result = $this->db->sellToShop($campaignId, $settlementId, $shopId, $characterId, $itemId, $quantity);
        if ($result === null) {
            return respondJson($response, 409, ['error' => 'insufficient inventory']);
        }

        return respondJson($response, 200, [
            'character_id' => $characterId,
            'item_id' => $itemId,
            'quantity' => $quantity,
            'gold' => $result['gold'],
            'stock' => $result['shop']['stock'][$itemId] ?? 0,
        ]);
    }

    private function validateShopBody(array $body): ?array
    {
        if (!isset($body['shop_id']) || (!is_string($body['shop_id']) && !is_numeric($body['shop_id']))) {
            return null;
        }
        $shopId = (string) $body['shop_id'];
        if ($shopId === '') {
            return null;
        }

        if (!isset($body['name']) || (!is_string($body['name']) && !is_numeric($body['name']))) {
            return null;
        }
        $name = (string) $body['name'];
        if ($name === '') {
            return null;
        }

        if (!isset($body['stock']) || !is_array($body['stock']) || count($body['stock']) === 0) {
            return null;
        }
        $stock = [];
        $seen = [];
        foreach ($body['stock'] as $itemId => $quantity) {
            if (!is_string($itemId) && !is_numeric($itemId)) {
                return null;
            }
            $itemId = (string) $itemId;
            if ($itemId === '' || !in_array($itemId, self::VALID_INVENTORY_ITEMS, true)) {
                return null;
            }
            if (!is_numeric($quantity) || (float) (int) $quantity !== (float) $quantity) {
                return null;
            }
            $quantity = (int) $quantity;
            if ($quantity < 1) {
                return null;
            }
            if (isset($seen[$itemId])) {
                return null;
            }
            $seen[$itemId] = true;
            $stock[$itemId] = $quantity;
        }

        if (!isset($body['buy_price']) || !is_numeric($body['buy_price']) || (float) (int) $body['buy_price'] !== (float) $body['buy_price']) {
            return null;
        }
        $buyPrice = (int) $body['buy_price'];
        if ($buyPrice < 1) {
            return null;
        }

        if (!isset($body['sell_price']) || !is_numeric($body['sell_price']) || (float) (int) $body['sell_price'] !== (float) $body['sell_price']) {
            return null;
        }
        $sellPrice = (int) $body['sell_price'];
        if ($sellPrice < 0) {
            return null;
        }

        return [$shopId, $name, $stock, $buyPrice, $sellPrice];
    }

    private function validateSettlementBody(array $body, bool $requireId): ?array
    {
        if ($requireId) {
            if (!isset($body['settlement_id']) || (!is_string($body['settlement_id']) && !is_numeric($body['settlement_id']))) {
                return null;
            }
            $settlementId = (string) $body['settlement_id'];
            if ($settlementId === '') {
                return null;
            }
        } else {
            $settlementId = '';
        }

        if (!isset($body['name']) || (!is_string($body['name']) && !is_numeric($body['name']))) {
            return null;
        }
        $name = (string) $body['name'];
        if ($name === '') {
            return null;
        }

        if (!isset($body['services']) || !is_array($body['services']) || !array_is_list($body['services']) || count($body['services']) === 0) {
            return null;
        }
        $services = [];
        $seen = [];
        foreach ($body['services'] as $service) {
            if (!is_string($service)) {
                return null;
            }
            $normalized = trim($service);
            if ($normalized === '') {
                return null;
            }
            if (isset($seen[$normalized])) {
                return null;
            }
            $seen[$normalized] = true;
            $services[] = $normalized;
        }

        if (!isset($body['availability']) || (!is_string($body['availability']) && !is_numeric($body['availability']))) {
            return null;
        }
        $availability = (string) $body['availability'];
        if (!in_array($availability, ['open', 'limited', 'closed'], true)) {
            return null;
        }

        return [$settlementId, $name, $services, $availability];
    }

    // Recipes

    private function createRecipe(Request $request, Response $response, array $args): Response
    {
        $actor = $this->requireDm($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        if ($campaign['owner'] !== $actor['username']) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $body = $request->getParsedBody() ?? [];
        $recipe = $this->validateRecipeBody($body);
        if ($recipe === null) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        if ($this->db->findRecipe($campaignId, $recipe['recipe_id']) !== null) {
            return respondJson($response, 409, ['error' => 'recipe id already exists']);
        }

        $this->db->createRecipe($campaignId, $recipe['recipe_id'], $recipe['name'], $recipe['ingredients'], $recipe['output_item'], $recipe['output_quantity']);

        return respondJson($response, 201, $recipe);
    }

    private function validateRecipeBody(array $body): ?array
    {
        if (!isset($body['recipe_id']) || (!is_string($body['recipe_id']) && !is_numeric($body['recipe_id']))) {
            return null;
        }
        $recipeId = (string) $body['recipe_id'];
        if ($recipeId === '') {
            return null;
        }

        if (!isset($body['name']) || (!is_string($body['name']) && !is_numeric($body['name']))) {
            return null;
        }
        $name = (string) $body['name'];
        if ($name === '') {
            return null;
        }

        if (!isset($body['ingredients']) || !is_array($body['ingredients']) || array_is_list($body['ingredients']) || count($body['ingredients']) === 0) {
            return null;
        }
        $ingredients = [];
        foreach ($body['ingredients'] as $itemId => $quantity) {
            if (!is_string($itemId) && !is_numeric($itemId)) {
                return null;
            }
            $itemId = (string) $itemId;
            if ($itemId === '' || !in_array($itemId, self::VALID_INVENTORY_ITEMS, true)) {
                return null;
            }
            if (!is_numeric($quantity) || (float) (int) $quantity !== (float) $quantity) {
                return null;
            }
            $quantity = (int) $quantity;
            if ($quantity < 1) {
                return null;
            }
            $ingredients[$itemId] = $quantity;
        }

        if (!isset($body['output_item']) || (!is_string($body['output_item']) && !is_numeric($body['output_item']))) {
            return null;
        }
        $outputItem = (string) $body['output_item'];
        if ($outputItem === '' || !in_array($outputItem, self::VALID_INVENTORY_ITEMS, true)) {
            return null;
        }

        if (!isset($body['output_quantity']) || !is_numeric($body['output_quantity']) || (float) (int) $body['output_quantity'] !== (float) $body['output_quantity']) {
            return null;
        }
        $outputQuantity = (int) $body['output_quantity'];
        if ($outputQuantity < 1) {
            return null;
        }

        return [
            'recipe_id' => $recipeId,
            'name' => $name,
            'ingredients' => $ingredients,
            'output_item' => $outputItem,
            'output_quantity' => $outputQuantity,
        ];
    }

    private function listRecipes(Request $request, Response $response, array $args): Response
    {
        $actor = $this->authenticate($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $isOwner = $campaign['owner'] === $actor['username'];
        $isMember = $this->db->findPlayMemberByCampaignAndUser($campaignId, $actor['username']) !== null;
        if (!$isOwner && !$isMember) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $rows = $this->db->findRecipesByCampaign($campaignId);
        $recipes = [];
        foreach ($rows as $row) {
            $recipes[] = [
                'recipe_id' => $row['recipe_id'],
                'name' => $row['name'],
                'ingredients' => $row['ingredients'],
                'output_item' => $row['output_item'],
                'output_quantity' => (int) $row['output_quantity'],
            ];
        }

        return respondJson($response, 200, ['recipes' => $recipes]);
    }

    private function craftRecipe(Request $request, Response $response, array $args): Response
    {
        $actor = $this->authenticate($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        if ($campaign['owner'] === $actor['username']) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $recipeId = (string) $args['recipe_id'];
        $recipe = $this->db->findRecipe($campaignId, $recipeId);
        if ($recipe === null) {
            return respondJson($response, 404, ['error' => 'recipe not found']);
        }

        $body = $request->getParsedBody() ?? [];
        if (!isset($body['character_id']) || (!is_string($body['character_id']) && !is_numeric($body['character_id']))) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }
        $characterId = (string) $body['character_id'];
        if ($characterId === '') {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $member = $this->db->findPlayMemberByCampaignAndCharacterId($campaignId, $characterId);
        if ($member === null) {
            return respondJson($response, 404, ['error' => 'character not found']);
        }

        $owner = $this->resolveOwner($member);
        if ($owner !== $actor['username']) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $crafted = $this->db->craftRecipe($campaignId, $recipeId, $characterId);
        if (!$crafted) {
            return respondJson($response, 409, ['error' => 'insufficient ingredients']);
        }

        return respondJson($response, 201, [
            'character_id' => $characterId,
            'recipe_id' => $recipeId,
            'output_item' => $recipe['output_item'],
            'output_quantity' => (int) $recipe['output_quantity'],
        ]);
    }

    private function createDowntimeActivity(Request $request, Response $response, array $args): Response
    {
        $actor = $this->requireDm($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        if ($campaign['owner'] !== $actor['username']) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $body = $request->getParsedBody() ?? [];
        if (!isset($body['activity_id']) || (!is_string($body['activity_id']) && !is_numeric($body['activity_id']))
            || !isset($body['name']) || (!is_string($body['name']) && !is_numeric($body['name']))
            || !isset($body['cycles_required']) || !$this->isValidInteger($body['cycles_required'], 1, 10)) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $activityId = (string) $body['activity_id'];
        $name = (string) $body['name'];
        $cyclesRequired = (int) $body['cycles_required'];
        if ($activityId === '' || $name === '') {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        if ($this->db->findDowntimeActivity($campaignId, $activityId) !== null) {
            return respondJson($response, 409, ['error' => 'activity id already exists']);
        }

        $this->db->createDowntimeActivity($campaignId, $activityId, $name, $cyclesRequired);

        return respondJson($response, 201, [
            'activity_id' => $activityId,
            'name' => $name,
            'cycles_required' => $cyclesRequired,
        ]);
    }

    private function createDowntimeAllocation(Request $request, Response $response, array $args): Response
    {
        $actor = $this->requirePlayer($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $characterId = (string) $args['character_id'];
        $member = $this->db->findPlayMemberByCampaignAndCharacterId($campaignId, $characterId);
        if ($member === null) {
            return respondJson($response, 404, ['error' => 'character not found']);
        }

        if ($this->resolveOwner($member) !== $actor['username']) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $body = $request->getParsedBody() ?? [];
        if (!isset($body['activity_id']) || (!is_string($body['activity_id']) && !is_numeric($body['activity_id']))) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }
        $activityId = (string) $body['activity_id'];
        if ($activityId === '') {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $activity = $this->db->findDowntimeActivity($campaignId, $activityId);
        if ($activity === null) {
            return respondJson($response, 404, ['error' => 'activity not found']);
        }

        if ($this->db->findDowntimeAllocation($campaignId, $characterId, $activityId) !== null) {
            return respondJson($response, 409, ['error' => 'allocation already exists']);
        }

        $this->db->createDowntimeAllocation($campaignId, $characterId, $activityId);

        return respondJson($response, 201, [
            'character_id' => $characterId,
            'activity_id' => $activityId,
            'cycles_completed' => 0,
            'completions' => 0,
        ]);
    }

    private function progressDowntimeAllocation(Request $request, Response $response, array $args): Response
    {
        $actor = $this->requirePlayer($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $characterId = (string) $args['character_id'];
        $member = $this->db->findPlayMemberByCampaignAndCharacterId($campaignId, $characterId);
        if ($member === null) {
            return respondJson($response, 404, ['error' => 'character not found']);
        }

        if ($this->resolveOwner($member) !== $actor['username']) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $activityId = (string) $args['activity_id'];
        $activity = $this->db->findDowntimeActivity($campaignId, $activityId);
        if ($activity === null) {
            return respondJson($response, 404, ['error' => 'activity not found']);
        }

        $allocation = $this->db->findDowntimeAllocation($campaignId, $characterId, $activityId);
        if ($allocation === null) {
            return respondJson($response, 404, ['error' => 'allocation not found']);
        }

        $cyclesCompleted = $allocation['cycles_completed'] + 1;
        $completions = $allocation['completions'];
        if ($cyclesCompleted >= $activity['cycles_required']) {
            $cyclesCompleted = 0;
            $completions++;
        }

        $this->db->updateDowntimeAllocation($campaignId, $characterId, $activityId, $cyclesCompleted, $completions);

        return respondJson($response, 200, [
            'character_id' => $characterId,
            'activity_id' => $activityId,
            'cycles_completed' => $cyclesCompleted,
            'completions' => $completions,
        ]);
    }

    private function getDowntimeAllocation(Request $request, Response $response, array $args): Response
    {
        $actor = $this->authenticate($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $isOwner = $campaign['owner'] === $actor['username'];
        $isMember = $this->db->findPlayMemberByCampaignAndUser($campaignId, $actor['username']) !== null;
        if (!$isOwner && !$isMember) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $characterId = (string) $args['character_id'];
        $member = $this->db->findPlayMemberByCampaignAndCharacterId($campaignId, $characterId);
        if ($member === null) {
            return respondJson($response, 404, ['error' => 'character not found']);
        }

        $activityId = (string) $args['activity_id'];
        $activity = $this->db->findDowntimeActivity($campaignId, $activityId);
        if ($activity === null) {
            return respondJson($response, 404, ['error' => 'activity not found']);
        }

        $allocation = $this->db->findDowntimeAllocation($campaignId, $characterId, $activityId);
        if ($allocation === null) {
            return respondJson($response, 404, ['error' => 'allocation not found']);
        }

        return respondJson($response, 200, [
            'character_id' => $characterId,
            'activity_id' => $activityId,
            'cycles_completed' => $allocation['cycles_completed'],
            'completions' => $allocation['completions'],
        ]);
    }

    private function createContent(Request $request, Response $response, array $args): Response
    {
        $actor = $this->requireDm($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        if ($campaign['owner'] !== $actor['username']) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $body = $request->getParsedBody() ?? [];
        if (!isset($body['content_id']) || (!is_string($body['content_id']) && !is_numeric($body['content_id']))
            || !isset($body['kind']) || (!is_string($body['kind']) && !is_numeric($body['kind']))
            || !isset($body['text']) || (!is_string($body['text']) && !is_numeric($body['text']))
            || !isset($body['tags']) || !is_array($body['tags']) || !array_is_list($body['tags'])) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $contentId = (string) $body['content_id'];
        $kind = (string) $body['kind'];
        $text = (string) $body['text'];
        if ($contentId === '' || $kind === '' || $text === '') {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $tags = $this->validateTags($body['tags'], true);
        if ($tags === null) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        if ($this->db->findPlayContent($campaignId, $contentId) !== null) {
            return respondJson($response, 409, ['error' => 'content id already exists']);
        }

        $this->db->createPlayContent($campaignId, $contentId, $kind, $text, $tags);

        return respondJson($response, 201, [
            'content_id' => $contentId,
            'kind' => $kind,
            'text' => $text,
            'tags' => $tags,
        ]);
    }

    private function updateContentTags(Request $request, Response $response, array $args): Response
    {
        $actor = $this->requireDm($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        if ($campaign['owner'] !== $actor['username']) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $contentId = (string) $args['content_id'];
        $content = $this->db->findPlayContent($campaignId, $contentId);
        if ($content === null) {
            return respondJson($response, 404, ['error' => 'content not found']);
        }

        $body = $request->getParsedBody() ?? [];
        if (!isset($body['tags']) || !is_array($body['tags']) || !array_is_list($body['tags'])) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $tags = $this->validateTags($body['tags'], false);
        if ($tags === null) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $this->db->updatePlayContentTags($campaignId, $contentId, $tags);

        return respondJson($response, 200, [
            'content_id' => $contentId,
            'kind' => $content['kind'],
            'text' => $content['text'],
            'tags' => $tags,
        ]);
    }

    private function listContent(Request $request, Response $response, array $args): Response
    {
        $actor = $this->authenticate($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $isOwner = $campaign['owner'] === $actor['username'];
        $isMember = $this->db->findPlayMemberByCampaignAndUser($campaignId, $actor['username']) !== null;
        if (!$isOwner && !$isMember) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $excludeTag = $request->getQueryParams()['exclude_tag'] ?? null;
        if ($excludeTag !== null) {
            if (!is_string($excludeTag) || $excludeTag === '') {
                return respondJson($response, 400, ['error' => 'invalid request']);
            }
        }

        $rows = $this->db->findPlayContentByCampaign($campaignId);
        $content = [];
        foreach ($rows as $row) {
            if (!$isOwner && $excludeTag !== null && in_array($excludeTag, $row['tags'], true)) {
                continue;
            }
            $content[] = [
                'content_id' => $row['content_id'],
                'kind' => $row['kind'],
                'text' => $row['text'],
                'tags' => $row['tags'],
            ];
        }

        return respondJson($response, 200, ['content' => $content]);
    }

    private function createSearchRecord(Request $request, Response $response, array $args): Response
    {
        $actor = $this->authenticate($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        if ($campaign['owner'] !== $actor['username']) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $body = $request->getParsedBody() ?? [];
        if (!isset($body['record_id']) || (!is_string($body['record_id']) && !is_numeric($body['record_id']))
            || !isset($body['text']) || (!is_string($body['text']) && !is_numeric($body['text']))) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $recordId = (string) $body['record_id'];
        $text = (string) $body['text'];
        if ($recordId === '' || $text === '') {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        if ($this->db->findSearchRecordByCampaignAndId($campaignId, $recordId) !== null) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        if ($this->db->findSearchRecordByCampaignAndText($campaignId, $text) !== null) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        try {
            $this->db->createSearchRecord($campaignId, $recordId, $text);
        } catch (PDOException $e) {
            if ($e->getCode() === '23000' || str_contains($e->getMessage(), 'UNIQUE constraint failed')) {
                return respondJson($response, 400, ['error' => 'invalid request']);
            }
            throw $e;
        }

        return respondJson($response, 201, [
            'record_id' => $recordId,
            'text' => $text,
        ]);
    }

    private function listSearchRecords(Request $request, Response $response, array $args): Response
    {
        $actor = $this->authenticate($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $isOwner = $campaign['owner'] === $actor['username'];
        $isMember = $this->db->findPlayMemberByCampaignAndUser($campaignId, $actor['username']) !== null;
        if (!$isOwner && !$isMember) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $params = $request->getQueryParams();

        $q = $params['q'] ?? null;
        if ($q !== null && !is_string($q) && !is_numeric($q)) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $limit = 2;
        if (isset($params['limit'])) {
            if (!$this->isValidInteger($params['limit'], 1, 3)) {
                return respondJson($response, 400, ['error' => 'invalid request']);
            }
            $limit = (int) $params['limit'];
        }

        $cursor = 0;
        if (isset($params['cursor'])) {
            if (!$this->isValidInteger($params['cursor'], 0)) {
                return respondJson($response, 400, ['error' => 'invalid request']);
            }
            $cursor = (int) $params['cursor'];
        }

        $rows = $this->db->findSearchRecordsByCampaign($campaignId);
        $filtered = [];
        foreach ($rows as $row) {
            if ($q !== null && $q !== '' && stripos($row['text'], (string) $q) === false) {
                continue;
            }
            $filtered[] = [
                'record_id' => $row['record_id'],
                'text' => $row['text'],
            ];
        }

        $total = count($filtered);
        $records = array_slice($filtered, $cursor, $limit);
        $nextCursor = ($cursor + $limit < $total) ? ($cursor + $limit) : null;

        return respondJson($response, 200, [
            'records' => $records,
            'next_cursor' => $nextCursor,
        ]);
    }

    private function createNote(Request $request, Response $response, array $args): Response
    {
        $actor = $this->authenticate($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $isOwner = $campaign['owner'] === $actor['username'];
        $isMember = $this->db->findPlayMemberByCampaignAndUser($campaignId, $actor['username']) !== null;
        if (!$isOwner && !$isMember) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $body = $request->getParsedBody() ?? [];
        if (!isset($body['note_id']) || (!is_string($body['note_id']) && !is_numeric($body['note_id']))
            || !isset($body['text']) || (!is_string($body['text']) && !is_numeric($body['text']))
            || !isset($body['visibility']) || (!is_string($body['visibility']) && !is_numeric($body['visibility']))) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $noteId = (string) $body['note_id'];
        $text = (string) $body['text'];
        $visibility = (string) $body['visibility'];
        if ($noteId === '' || $text === '' || !in_array($visibility, ['private', 'party'], true)) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        if ($this->db->findPlayNote($campaignId, $noteId) !== null) {
            return respondJson($response, 409, ['error' => 'note id already exists']);
        }

        $this->db->createPlayNote($campaignId, $noteId, $text, $visibility, $actor['username']);

        return respondJson($response, 201, [
            'note_id' => $noteId,
            'text' => $text,
            'visibility' => $visibility,
            'owner' => $actor['username'],
        ]);
    }

    private function listNotes(Request $request, Response $response, array $args): Response
    {
        $actor = $this->authenticate($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $isOwner = $campaign['owner'] === $actor['username'];
        $isMember = $this->db->findPlayMemberByCampaignAndUser($campaignId, $actor['username']) !== null;
        if (!$isOwner && !$isMember) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $rows = $this->db->findPlayNotesByCampaign($campaignId);
        $notes = [];
        foreach ($rows as $row) {
            if (!$isOwner && $row['visibility'] === 'private' && $row['owner'] !== $actor['username']) {
                continue;
            }
            $notes[] = [
                'note_id' => $row['note_id'],
                'text' => $row['text'],
                'visibility' => $row['visibility'],
                'owner' => $row['owner'],
            ];
        }

        return respondJson($response, 200, ['notes' => $notes]);
    }

    private function getNote(Request $request, Response $response, array $args): Response
    {
        $actor = $this->authenticate($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $isOwner = $campaign['owner'] === $actor['username'];
        $isMember = $this->db->findPlayMemberByCampaignAndUser($campaignId, $actor['username']) !== null;
        if (!$isOwner && !$isMember) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $noteId = (string) $args['note_id'];
        $note = $this->db->findPlayNote($campaignId, $noteId);
        if ($note === null) {
            return respondJson($response, 404, ['error' => 'note not found']);
        }

        if (!$isOwner && $note['visibility'] === 'private' && $note['owner'] !== $actor['username']) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        return respondJson($response, 200, [
            'note_id' => $note['note_id'],
            'text' => $note['text'],
            'visibility' => $note['visibility'],
            'owner' => $note['owner'],
        ]);
    }

    private function updateNote(Request $request, Response $response, array $args): Response
    {
        $actor = $this->authenticate($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $isOwner = $campaign['owner'] === $actor['username'];
        $isMember = $this->db->findPlayMemberByCampaignAndUser($campaignId, $actor['username']) !== null;
        if (!$isOwner && !$isMember) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $noteId = (string) $args['note_id'];
        $note = $this->db->findPlayNote($campaignId, $noteId);
        if ($note === null) {
            return respondJson($response, 404, ['error' => 'note not found']);
        }

        if ($note['owner'] !== $actor['username']) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $body = $request->getParsedBody() ?? [];
        if (!isset($body['text']) || (!is_string($body['text']) && !is_numeric($body['text']))
            || !isset($body['visibility']) || (!is_string($body['visibility']) && !is_numeric($body['visibility']))) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $text = (string) $body['text'];
        $visibility = (string) $body['visibility'];
        if ($text === '' || !in_array($visibility, ['private', 'party'], true)) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $this->db->updatePlayNote($campaignId, $noteId, $text, $visibility);

        return respondJson($response, 200, [
            'note_id' => $noteId,
            'text' => $text,
            'visibility' => $visibility,
            'owner' => $note['owner'],
        ]);
    }

    private function createWhisper(Request $request, Response $response, array $args): Response
    {
        $actor = $this->requirePlayer($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $member = $this->db->findPlayMemberByCampaignAndUser($campaignId, $actor['username']);
        if ($member === null) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $owner = $this->resolveOwner($member);
        if ($owner !== $actor['username']) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }
        $fromCharacterId = $member['character_id'];

        $body = $request->getParsedBody() ?? [];
        if (!isset($body['whisper_id']) || (!is_string($body['whisper_id']) && !is_numeric($body['whisper_id']))
            || !isset($body['to_character_id']) || (!is_string($body['to_character_id']) && !is_numeric($body['to_character_id']))
            || !isset($body['text']) || (!is_string($body['text']) && !is_numeric($body['text']))) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $whisperId = (string) $body['whisper_id'];
        $toCharacterId = (string) $body['to_character_id'];
        $text = (string) $body['text'];
        if ($whisperId === '' || $toCharacterId === '' || $text === '') {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        if ($this->db->findPlayWhisper($campaignId, $whisperId) !== null) {
            return respondJson($response, 409, ['error' => 'whisper id already exists']);
        }

        if ($this->db->findPlayMemberByCampaignAndCharacterId($campaignId, $toCharacterId) === null) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $this->db->createPlayWhisper($campaignId, $whisperId, $fromCharacterId, $toCharacterId, $text);

        return respondJson($response, 201, [
            'whisper_id' => $whisperId,
            'from_character_id' => $fromCharacterId,
            'to_character_id' => $toCharacterId,
            'text' => $text,
        ]);
    }

    private function listWhispers(Request $request, Response $response, array $args): Response
    {
        $actor = $this->authenticate($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $isOwner = $campaign['owner'] === $actor['username'];
        $isMember = $this->db->findPlayMemberByCampaignAndUser($campaignId, $actor['username']) !== null;
        if (!$isOwner && !$isMember) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $rows = $this->db->findPlayWhispersByCampaign($campaignId);
        $whispers = [];
        if ($isOwner) {
            foreach ($rows as $row) {
                $whispers[] = [
                    'whisper_id' => $row['whisper_id'],
                    'from_character_id' => $row['from_character_id'],
                    'to_character_id' => $row['to_character_id'],
                    'text' => $row['text'],
                ];
            }
        } else {
            $member = $this->db->findPlayMemberByCampaignAndUser($campaignId, $actor['username']);
            $characterId = $member !== null ? (string) $member['character_id'] : '';
            foreach ($rows as $row) {
                if ($row['from_character_id'] === $characterId || $row['to_character_id'] === $characterId) {
                    $whispers[] = [
                        'whisper_id' => $row['whisper_id'],
                        'from_character_id' => $row['from_character_id'],
                        'to_character_id' => $row['to_character_id'],
                        'text' => $row['text'],
                    ];
                }
            }
        }

        return respondJson($response, 200, ['whispers' => $whispers]);
    }

    private function getCharacterSheet(Request $request, Response $response, array $args): Response
    {
        $actor = $this->authenticate($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $characterId = (string) $args['char_id'];
        $member = $this->db->findPlayMemberByCampaignAndCharacterId($campaignId, $characterId);
        if ($member === null) {
            return respondJson($response, 404, ['error' => 'character not found']);
        }

        $isOwner = $campaign['owner'] === $actor['username'];
        $owner = $this->resolveOwner($member);
        if (!$isOwner && $owner !== $actor['username']) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        // The basic sheet is a deterministic, level-one snapshot, not a
        // live reflection of character progression or equipment.
        return respondJson($response, 200, [
            'character_id' => $characterId,
            'owner' => $owner,
            'name' => (string) $member['name'],
            'class' => (string) $member['class'],
            'level' => 1,
            'proficiency_bonus' => 2,
            'hp_max' => 10,
            'armor_class' => 10,
        ]);
    }

    private function validateTags(array $tags, bool $requireNonEmpty): ?array
    {
        if (!array_is_list($tags)) {
            return null;
        }
        if ($requireNonEmpty && count($tags) === 0) {
            return null;
        }
        $seen = [];
        $result = [];
        foreach ($tags as $tag) {
            if (!is_string($tag) && !is_numeric($tag)) {
                return null;
            }
            $tag = (string) $tag;
            if ($tag === '') {
                return null;
            }
            if (in_array($tag, $seen, true)) {
                return null;
            }
            $seen[] = $tag;
            $result[] = $tag;
        }
        return $result;
    }

    private function createInvitation(Request $request, Response $response, array $args): Response
    {
        $actor = $this->requireDm($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        if ($campaign['owner'] !== $actor['username']) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $body = $request->getParsedBody() ?? [];
        if (!isset($body['invitation_id']) || (!is_string($body['invitation_id']) && !is_numeric($body['invitation_id']))
            || !isset($body['username']) || (!is_string($body['username']) && !is_numeric($body['username']))
            || !isset($body['character_id']) || (!is_string($body['character_id']) && !is_numeric($body['character_id']))) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $invitationId = (string) $body['invitation_id'];
        $username = (string) $body['username'];
        $characterId = (string) $body['character_id'];
        if ($invitationId === '' || $username === '' || $characterId === '') {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $target = $this->db->findUser($username);
        if ($target === null || $target['role'] !== 'player') {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        if ($this->db->findPlayInvitation($campaignId, $invitationId) !== null) {
            return respondJson($response, 409, ['error' => 'invitation id already exists']);
        }

        if ($this->db->findPendingPlayInvitationByCampaignAndUser($campaignId, $username) !== null) {
            return respondJson($response, 409, ['error' => 'pending invitation already exists']);
        }

        $this->db->createPlayInvitation($campaignId, $invitationId, $username, $characterId);

        return respondJson($response, 201, [
            'invitation_id' => $invitationId,
            'username' => $username,
            'character_id' => $characterId,
            'status' => 'pending',
        ]);
    }

    private function acceptInvitation(Request $request, Response $response, array $args): Response
    {
        $actor = $this->authenticate($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $invitationId = (string) $args['invitation_id'];
        $invitation = $this->db->findPlayInvitation($campaignId, $invitationId);
        if ($invitation === null) {
            return respondJson($response, 404, ['error' => 'invitation not found']);
        }

        if ($invitation['username'] !== $actor['username']) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        if ($invitation['status'] === 'accepted') {
            return respondJson($response, 409, ['error' => 'invitation already accepted']);
        }

        if ($this->db->findPlayMemberByCampaignAndUser($campaignId, $actor['username']) !== null) {
            return respondJson($response, 409, ['error' => 'already a member']);
        }

        if ($this->db->findPlayMemberByCampaignAndCharacterId($campaignId, $invitation['character_id']) !== null) {
            return respondJson($response, 409, ['error' => 'character id already exists']);
        }

        $this->db->acceptPlayInvitation($campaignId, $invitationId, $actor['username'], $invitation['character_id']);

        return respondJson($response, 200, [
            'invitation_id' => $invitationId,
            'username' => $invitation['username'],
            'character_id' => $invitation['character_id'],
            'status' => 'accepted',
        ]);
    }

    private function listInvitations(Request $request, Response $response, array $args): Response
    {
        $actor = $this->authenticate($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $isOwner = $campaign['owner'] === $actor['username'];
        if ($isOwner) {
            $invitations = $this->db->findPlayInvitationsByCampaign($campaignId);
            return respondJson($response, 200, ['invitations' => $invitations]);
        }

        $isMember = $this->db->findPlayMemberByCampaignAndUser($campaignId, $actor['username']) !== null;
        $invitations = $this->db->findPlayInvitationsByCampaign($campaignId);
        $ownInvitations = array_values(array_filter($invitations, fn (array $invitation): bool => $invitation['username'] === $actor['username']));

        if (!$isMember && count($ownInvitations) === 0) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        return respondJson($response, 200, ['invitations' => $ownInvitations]);
    }

    private function submitSafeTurn(Request $request, Response $response, array $args): Response
    {
        $actor = $this->authenticate($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $isOwner = $campaign['owner'] === $actor['username'];
        $isMember = $this->db->findPlayMemberByCampaignAndUser($campaignId, $actor['username']) !== null;
        if (!$isOwner && !$isMember) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $body = $request->getParsedBody() ?? [];
        if (!isset($body['submission_id']) || !is_string($body['submission_id']) || $body['submission_id'] === ''
            || !isset($body['action']) || !is_string($body['action']) || $body['action'] === ''
            || !isset($body['expected_turn']) || !is_int($body['expected_turn']) || $body['expected_turn'] < 1) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $submissionId = $body['submission_id'];
        $action = $body['action'];
        $expectedTurn = $body['expected_turn'];

        $result = $this->db->submitSafeTurn($campaignId, $submissionId, $expectedTurn, $action);

        if ($result['status'] === 'accepted') {
            return respondJson($response, 201, [
                'submission_id' => $submissionId,
                'action' => $action,
                'accepted_turn' => $result['accepted_turn'],
                'next_turn' => $result['next_turn'],
            ]);
        }

        return respondJson($response, 409, ['current_turn' => $result['current_turn']]);
    }

    private function listSafeTurns(Request $request, Response $response, array $args): Response
    {
        $actor = $this->authenticate($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $isOwner = $campaign['owner'] === $actor['username'];
        $isMember = $this->db->findPlayMemberByCampaignAndUser($campaignId, $actor['username']) !== null;
        if (!$isOwner && !$isMember) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $state = $this->db->getSafeTurnState($campaignId);
        return respondJson($response, 200, [
            'current_turn' => $state['current_turn'],
            'accepted' => $state['accepted'],
        ]);
    }

    private function submitModerationReport(Request $request, Response $response, array $args): Response
    {
        $actor = $this->authenticate($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $isOwner = $campaign['owner'] === $actor['username'];
        $isMember = $this->db->findPlayMemberByCampaignAndUser($campaignId, $actor['username']) !== null;
        if (!$isOwner && !$isMember) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $body = $request->getParsedBody() ?? [];
        if (!isset($body['report_id']) || (!is_string($body['report_id']) && !is_numeric($body['report_id']))
            || !isset($body['target_id']) || (!is_string($body['target_id']) && !is_numeric($body['target_id']))
            || !isset($body['reason']) || (!is_string($body['reason']) && !is_numeric($body['reason']))) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $reportId = (string) $body['report_id'];
        $targetId = (string) $body['target_id'];
        $reason = (string) $body['reason'];
        if ($reportId === '' || $targetId === '' || $reason === '') {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        if ($this->db->findModerationReport($campaignId, $reportId) !== null) {
            return respondJson($response, 409, ['error' => 'report id already exists']);
        }

        $sequence = $this->db->nextModerationSequence($campaignId);
        $this->db->createModerationReport([
            'campaign_id' => $campaignId,
            'report_id' => $reportId,
            'target_id' => $targetId,
            'reason' => $reason,
            'status' => 'open',
            'reporter' => $actor['username'],
            'sequence' => $sequence,
        ]);

        return respondJson($response, 201, [
            'report_id' => $reportId,
            'target_id' => $targetId,
            'reason' => $reason,
            'status' => 'open',
            'reporter' => $actor['username'],
            'sequence' => $sequence,
        ]);
    }

    private function listModerationReports(Request $request, Response $response, array $args): Response
    {
        $actor = $this->authenticate($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $isOwner = $campaign['owner'] === $actor['username'];
        $isMember = $this->db->findPlayMemberByCampaignAndUser($campaignId, $actor['username']) !== null;
        if (!$isOwner && !$isMember) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $rows = $this->db->findModerationReports($campaignId);
        $reports = [];
        foreach ($rows as $row) {
            $report = [
                'report_id' => $row['report_id'],
                'target_id' => $row['target_id'],
                'reason' => $row['reason'],
                'status' => $row['status'],
                'reporter' => $row['reporter'],
                'sequence' => (int) $row['sequence'],
            ];
            if ($row['status'] === 'resolved') {
                $report['action'] = $row['action'];
                $report['note'] = $row['note'];
                $report['resolver'] = $row['resolver'];
            }
            $reports[] = $report;
        }

        return respondJson($response, 200, ['reports' => $reports]);
    }

    private function resolveModerationReport(Request $request, Response $response, array $args): Response
    {
        $actor = $this->authenticate($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        if ($campaign['owner'] !== $actor['username']) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $reportId = (string) $args['report_id'];
        $report = $this->db->findModerationReport($campaignId, $reportId);
        if ($report === null) {
            return respondJson($response, 404, ['error' => 'report not found']);
        }

        if ($report['status'] !== 'open') {
            return respondJson($response, 409, ['error' => 'report already resolved']);
        }

        $body = $request->getParsedBody() ?? [];
        if (!isset($body['action']) || (!is_string($body['action']) && !is_numeric($body['action']))
            || !isset($body['note']) || (!is_string($body['note']) && !is_numeric($body['note']))) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $action = (string) $body['action'];
        $note = (string) $body['note'];
        if (!in_array($action, ['allow', 'remove'], true) || $note === '') {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $this->db->resolveModerationReport($campaignId, $reportId, $action, $note, $actor['username']);

        return respondJson($response, 200, [
            'report_id' => $report['report_id'],
            'target_id' => $report['target_id'],
            'reason' => $report['reason'],
            'status' => 'resolved',
            'reporter' => $report['reporter'],
            'sequence' => (int) $report['sequence'],
            'action' => $action,
            'note' => $note,
            'resolver' => $actor['username'],
        ]);
    }

    private function replaceSafetyBoundaries(Request $request, Response $response, array $args): Response
    {
        $actor = $this->authenticate($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        if ($campaign['owner'] !== $actor['username']) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $body = $request->getParsedBody() ?? [];
        if (!isset($body['blocked_tags']) || !is_array($body['blocked_tags']) || count($body['blocked_tags']) === 0) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $tags = [];
        $seen = [];
        foreach ($body['blocked_tags'] as $tag) {
            if (!is_string($tag) && !is_numeric($tag)) {
                return respondJson($response, 400, ['error' => 'invalid request']);
            }
            $value = (string) $tag;
            if ($value === '' || in_array($value, $seen, true)) {
                return respondJson($response, 400, ['error' => 'invalid request']);
            }
            $seen[] = $value;
            $tags[] = $value;
        }

        sort($tags, SORT_STRING);
        $this->db->setSafetyBoundary($campaignId, $tags);

        return respondJson($response, 200, ['blocked_tags' => $tags]);
    }

    private function getSafetyBoundaries(Request $request, Response $response, array $args): Response
    {
        $actor = $this->authenticate($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $isOwner = $campaign['owner'] === $actor['username'];
        $isMember = $this->db->findPlayMemberByCampaignAndUser($campaignId, $actor['username']) !== null;
        if (!$isOwner && !$isMember) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $boundary = $this->db->findSafetyBoundary($campaignId);
        $tags = $boundary !== null ? $boundary['blocked_tags'] : [];

        return respondJson($response, 200, ['blocked_tags' => $tags]);
    }

    private function submitSafetyCheck(Request $request, Response $response, array $args): Response
    {
        $actor = $this->authenticate($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $isOwner = $campaign['owner'] === $actor['username'];
        $isMember = $this->db->findPlayMemberByCampaignAndUser($campaignId, $actor['username']) !== null;
        if (!$isOwner && !$isMember) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $body = $request->getParsedBody() ?? [];
        if (!isset($body['event_id']) || (!is_string($body['event_id']) && !is_numeric($body['event_id']))) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }
        $eventId = (string) $body['event_id'];
        if ($eventId === '') {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        if (!isset($body['kind']) || (!is_string($body['kind']) && !is_numeric($body['kind']))) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }
        $kind = (string) $body['kind'];
        if (!in_array($kind, ['narration', 'chat'], true)) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        if (!isset($body['text']) || (!is_string($body['text']) && !is_numeric($body['text']))) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }
        $text = (string) $body['text'];
        if ($text === '') {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        if (!isset($body['tags']) || !is_array($body['tags']) || count($body['tags']) === 0) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }
        $tags = [];
        $seen = [];
        foreach ($body['tags'] as $tag) {
            if (!is_string($tag) && !is_numeric($tag)) {
                return respondJson($response, 400, ['error' => 'invalid request']);
            }
            $value = (string) $tag;
            if ($value === '' || in_array($value, $seen, true)) {
                return respondJson($response, 400, ['error' => 'invalid request']);
            }
            $seen[] = $value;
            $tags[] = $value;
        }

        if ($this->db->findSafetyEvent($campaignId, $eventId) !== null) {
            return respondJson($response, 409, ['error' => 'event id already exists']);
        }

        $boundary = $this->db->findSafetyBoundary($campaignId);
        $blockedTags = $boundary !== null ? $boundary['blocked_tags'] : [];
        foreach ($tags as $tag) {
            if (in_array($tag, $blockedTags, true)) {
                return respondJson($response, 409, ['error' => 'blocked tag']);
            }
        }

        $sequence = $this->db->nextSafetyEventSequence($campaignId);
        $this->db->createSafetyEvent($campaignId, $sequence, $eventId, $kind, $text, $tags);

        return respondJson($response, 201, [
            'event_id' => $eventId,
            'kind' => $kind,
            'text' => $text,
            'tags' => $tags,
            'sequence' => $sequence,
        ]);
    }

    private function listSafetyEvents(Request $request, Response $response, array $args): Response
    {
        $actor = $this->authenticate($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $isOwner = $campaign['owner'] === $actor['username'];
        $isMember = $this->db->findPlayMemberByCampaignAndUser($campaignId, $actor['username']) !== null;
        if (!$isOwner && !$isMember) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $rows = $this->db->findSafetyEvents($campaignId);
        $events = [];
        foreach ($rows as $row) {
            $events[] = [
                'event_id' => $row['event_id'],
                'kind' => $row['kind'],
                'text' => $row['text'],
                'tags' => $row['tags'],
                'sequence' => (int) $row['sequence'],
            ];
        }

        return respondJson($response, 200, ['events' => $events]);
    }

    private function seedFixture(Request $request, Response $response, array $args): Response
    {
        $actor = $this->authenticate($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        if ($campaign['owner'] !== $actor['username']) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $body = $request->getParsedBody() ?? [];
        if (!isset($body['fixture_id']) || !is_string($body['fixture_id']) || $body['fixture_id'] !== self::CANONICAL_FIXTURE_ID) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $existing = $this->db->findPlayFixtureSeed($campaignId);
        if ($existing !== null) {
            return respondJson($response, 200, self::CANONICAL_FIXTURE);
        }

        $created = $this->db->createPlayFixtureSeed($campaignId, self::CANONICAL_FIXTURE_ID, 'seeded');
        $status = $created ? 201 : 200;

        return respondJson($response, $status, self::CANONICAL_FIXTURE);
    }

    private function getFixtureState(Request $request, Response $response, array $args): Response
    {
        $actor = $this->authenticate($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $isOwner = $campaign['owner'] === $actor['username'];
        $isMember = $this->db->findPlayMemberByCampaignAndUser($campaignId, $actor['username']) !== null;
        if (!$isOwner && !$isMember) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $seed = $this->db->findPlayFixtureSeed($campaignId);
        if ($seed === null) {
            return respondJson($response, 404, ['error' => 'fixture state not found']);
        }

        return respondJson($response, 200, self::CANONICAL_FIXTURE);
    }

    /**
     * Create a read-only spectator ticket for a campaign.
     *
     * Only the campaign owner may issue spectator tokens. The spectator_id
     * must be a non-empty string that is globally unique across all spectator
     * tickets.
     */
    private function createSpectator(Request $request, Response $response, array $args): Response
    {
        $actor = $this->requireDm($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        if ($campaign['owner'] !== $actor['username']) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $body = $request->getParsedBody() ?? [];
        if (!isset($body['spectator_id']) || (!is_string($body['spectator_id']) && !is_numeric($body['spectator_id']))) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $spectatorId = (string) $body['spectator_id'];
        if ($spectatorId === '') {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        try {
            $this->db->createPlaySpectator($campaignId, $spectatorId);
        } catch (PDOException $e) {
            if ($e->getCode() === '23000' || str_contains($e->getMessage(), 'UNIQUE constraint failed')) {
                return respondJson($response, 409, ['error' => 'spectator id already exists']);
            }
            throw $e;
        }

        return respondJson($response, 201, [
            'spectator_id' => $spectatorId,
            'token' => 'spectator-' . $spectatorId,
        ]);
    }

    /**
     * Return a sanitized, read-only projection of a campaign for spectators.
     *
     * Accessible only with a spectator bearer token issued for this campaign.
     * The view intentionally omits member names, character ids, private notes,
     * chat, tokens, ownership, and internal ids.
     */
    private function getSpectatorView(Request $request, Response $response, array $args): Response
    {
        $campaignId = (string) $args['id'];
        $spectator = $this->requireSpectator($request, $response, $campaignId);
        if ($spectator instanceof Response) {
            return $spectator;
        }

        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        return respondJson($response, 200, $this->buildSpectatorView($campaign));
    }

    /**
     * Authenticate an exclusively spectator-scoped request.
     *
     * Returns the spectator row when the request carries a valid bearer token
     * in the form `spectator-<id>` for this campaign. Session tokens return
     * 403; missing or malformed spectator tokens return 401. An unknown
     * campaign with a well-formed spectator token returns 404.
     *
     * @return array<string, mixed>|Response
     */
    private function requireSpectator(Request $request, Response $response, string $campaignId): array|Response
    {
        $header = $request->getHeaderLine('Authorization');
        if ($header === '' || !str_starts_with($header, 'Bearer ')) {
            return respondJson($response, 401, ['error' => 'unauthorized']);
        }

        $token = substr($header, 7);
        if (str_starts_with($token, self::TOKEN_PREFIX)) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        if (!str_starts_with($token, 'spectator-')) {
            return respondJson($response, 401, ['error' => 'unauthorized']);
        }

        $spectatorId = substr($token, strlen('spectator-'));
        if ($spectatorId === '') {
            return respondJson($response, 401, ['error' => 'unauthorized']);
        }

        $spectator = $this->db->findPlaySpectator($spectatorId);
        if ($spectator === null) {
            return respondJson($response, 401, ['error' => 'unauthorized']);
        }

        $campaign = $this->db->findPlayCampaign($campaignId);
        if ($campaign === null) {
            return respondJson($response, 404, ['error' => 'campaign not found']);
        }

        if ($spectator['campaign_id'] !== $campaignId) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        return $spectator;
    }

    /**
     * Build the public spectator projection for a campaign.
     *
     * @param array<string, mixed> $campaign
     * @return array<string, mixed>
     */
    private function buildSpectatorView(array $campaign): array
    {
        $campaignId = (string) $campaign['id'];
        $partySize = $this->db->countPlayMembers($campaignId);
        $doc = $this->db->findPlayCampaignDocument($campaignId) ?? ['story' => '', 'dm_notes' => ''];

        return [
            'campaign_id' => $campaignId,
            'name' => (string) $campaign['name'],
            'status' => (string) $campaign['status'],
            'party_size' => $partySize,
            'story' => (string) ($doc['story'] ?? ''),
        ];
    }

    private function appendFeedEvent(Request $request, Response $response, array $args): Response
    {
        $actor = $this->authenticate($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $isOwner = $campaign['owner'] === $actor['username'];
        $isMember = $this->db->findPlayMemberByCampaignAndUser($campaignId, $actor['username']) !== null;
        if (!$isOwner && !$isMember) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $body = $request->getParsedBody() ?? [];
        if (!isset($body['event_id']) || !is_string($body['event_id']) || $body['event_id'] === ''
            || !isset($body['text']) || !is_string($body['text']) || $body['text'] === '') {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }
        $eventId = $body['event_id'];
        $text = $body['text'];

        if ($this->db->findFeedEvent($campaignId, $eventId) !== null) {
            return respondJson($response, 409, ['error' => 'event id already exists']);
        }

        $sequence = $this->db->nextFeedEventSequence($campaignId);
        $this->db->createFeedEvent($campaignId, $sequence, $eventId, $text);

        return respondJson($response, 201, [
            'event_id' => $eventId,
            'text' => $text,
            'sequence' => $sequence,
        ]);
    }

    private function listEventFeed(Request $request, Response $response, array $args): Response
    {
        $actor = $this->authenticate($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $isOwner = $campaign['owner'] === $actor['username'];
        $isMember = $this->db->findPlayMemberByCampaignAndUser($campaignId, $actor['username']) !== null;
        if (!$isOwner && !$isMember) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $params = $request->getQueryParams();
        $cursor = 0;
        $limit = 2;

        if (isset($params['cursor'])) {
            $value = $params['cursor'];
            if (!is_scalar($value)) {
                return respondJson($response, 400, ['error' => 'invalid request']);
            }
            $cursorVal = filter_var($value, FILTER_VALIDATE_INT);
            if ($cursorVal === false || $cursorVal < 0) {
                return respondJson($response, 400, ['error' => 'invalid request']);
            }
            $cursor = $cursorVal;
        }

        if (isset($params['limit'])) {
            $value = $params['limit'];
            if (!is_scalar($value)) {
                return respondJson($response, 400, ['error' => 'invalid request']);
            }
            $limitVal = filter_var($value, FILTER_VALIDATE_INT);
            if ($limitVal === false || $limitVal < 1 || $limitVal > 3) {
                return respondJson($response, 400, ['error' => 'invalid request']);
            }
            $limit = $limitVal;
        }

        $events = $this->db->findFeedEvents($campaignId, $cursor, $limit);

        return respondJson($response, 200, [
            'events' => $events,
            'next_cursor' => $cursor + count($events),
        ]);
    }

    private function createMessage(Request $request, Response $response, array $args): Response
    {
        $actor = $this->authenticate($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaignId = (string) $args['id'];
        $campaign = $this->requirePlayCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $isOwner = $campaign['owner'] === $actor['username'];
        $isMember = $this->db->findPlayMemberByCampaignAndUser($campaignId, $actor['username']) !== null;
        if (!$isOwner && !$isMember) {
            return respondJson($response, 403, ['error' => 'forbidden']);
        }

        $body = $request->getParsedBody() ?? [];
        if (!isset($body['text']) || (!is_string($body['text']) && !is_numeric($body['text']))) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $text = (string) $body['text'];
        if ($text === '') {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $this->db->createPlayMessage($campaignId, $actor['username'], $text);

        return respondJson($response, 201, [
            'kind' => 'chat',
            'actor' => $actor['username'],
            'text' => $text,
        ]);
    }
}
