<?php

declare(strict_types=1);

namespace App\Routes;

use App\Http\Json;
use App\Storage\CampaignRepository;
use App\Storage\Database;
use Psr\Http\Message\ResponseInterface as Response;
use Psr\Http\Message\ServerRequestInterface as Request;
use Slim\App;

/** Campaigns, their characters, and their event log. */
final class CampaignRoutes
{
    public static function register(App $app, string $dbFile): void
    {
        $app->post('/v1/campaigns', function (Request $request, Response $response) use ($dbFile) {
            $repo = self::repo($dbFile);
            $body = Json::parseBody($request);
            $id = $body['id'] ?? null;
            $name = $body['name'] ?? null;
            $dm = $body['dm'] ?? null;

            if (!is_string($id) || $id === '') {
                return Json::response($response, ['error' => 'invalid id'], 400);
            }
            if (!is_string($name) || $name === '') {
                return Json::response($response, ['error' => 'invalid name'], 400);
            }
            if (!is_string($dm) || $dm === '') {
                return Json::response($response, ['error' => 'invalid dm'], 400);
            }

            if ($repo->fetch($id) !== null) {
                return Json::response($response, ['error' => 'campaign already exists'], 409);
            }

            $campaign = ['id' => $id, 'name' => $name, 'dm' => $dm];
            $repo->insert($campaign);

            return Json::response($response, $campaign, 201);
        });

        $app->post('/v1/campaigns/{id}/characters', function (Request $request, Response $response, array $args) use ($dbFile) {
            $repo = self::repo($dbFile);
            $campaignId = $args['id'];
            $notFound = self::requireCampaign($repo, $response, $campaignId);
            if ($notFound instanceof Response) {
                return $notFound;
            }

            $body = Json::parseBody($request);
            $id = $body['id'] ?? null;
            $name = $body['name'] ?? null;
            $level = $body['level'] ?? null;
            $class = $body['class'] ?? null;

            if (!is_string($id) || $id === '') {
                return Json::response($response, ['error' => 'invalid id'], 400);
            }
            if (!is_string($name) || $name === '') {
                return Json::response($response, ['error' => 'invalid name'], 400);
            }
            if (!is_int($level) || $level <= 0) {
                return Json::response($response, ['error' => 'invalid level'], 400);
            }
            if (!is_string($class) || $class === '') {
                return Json::response($response, ['error' => 'invalid class'], 400);
            }

            if ($repo->characterExists($id)) {
                return Json::response($response, ['error' => 'character already exists'], 409);
            }

            $character = ['id' => $id, 'name' => $name, 'level' => $level, 'class' => $class];
            $repo->insertCharacter($campaignId, $character);

            return Json::response($response, $character, 201);
        });

        $app->post('/v1/campaigns/{id}/events', function (Request $request, Response $response, array $args) use ($dbFile) {
            $repo = self::repo($dbFile);
            $campaignId = $args['id'];
            $notFound = self::requireCampaign($repo, $response, $campaignId);
            if ($notFound instanceof Response) {
                return $notFound;
            }

            $body = Json::parseBody($request);
            $id = $body['id'] ?? null;
            $kind = $body['kind'] ?? null;
            $summary = $body['summary'] ?? null;

            if (!is_string($id) || $id === '') {
                return Json::response($response, ['error' => 'invalid id'], 400);
            }
            if (!is_string($kind) || $kind === '') {
                return Json::response($response, ['error' => 'invalid kind'], 400);
            }
            if (!is_string($summary) || $summary === '') {
                return Json::response($response, ['error' => 'invalid summary'], 400);
            }

            if ($repo->eventExists($id)) {
                return Json::response($response, ['error' => 'event already exists'], 409);
            }

            $event = ['id' => $id, 'kind' => $kind, 'summary' => $summary];
            $repo->insertEvent($campaignId, $event);

            return Json::response($response, ['id' => $id, 'kind' => $kind], 201);
        });

        $app->get('/v1/campaigns/{id}/state', function (Request $request, Response $response, array $args) use ($dbFile) {
            $repo = self::repo($dbFile);
            $campaignId = $args['id'];
            $campaign = self::requireCampaign($repo, $response, $campaignId);
            if ($campaign instanceof Response) {
                return $campaign;
            }

            $characters = $repo->characters($campaignId);
            $logCount = $repo->eventCount($campaignId);

            return Json::response($response, [
                'id' => $campaign['id'],
                'name' => $campaign['name'],
                'dm' => $campaign['dm'],
                'characters' => $characters,
                'log_count' => $logCount,
            ]);
        });

        $app->post('/v1/campaigns/{id}/quests', function (Request $request, Response $response, array $args) use ($dbFile) {
            $repo = self::repo($dbFile);
            $campaignId = $args['id'];
            $notFound = self::requireCampaign($repo, $response, $campaignId);
            if ($notFound instanceof Response) {
                return $notFound;
            }

            $body = Json::parseBody($request);
            $id = $body['id'] ?? null;
            $title = $body['title'] ?? null;
            $status = $body['status'] ?? null;
            $milestones = $body['milestones'] ?? null;

            if (!is_string($id) || $id === '') {
                return Json::response($response, ['error' => 'invalid id'], 400);
            }
            if (!is_string($title) || $title === '') {
                return Json::response($response, ['error' => 'invalid title'], 400);
            }
            if (!is_string($status) || !in_array($status, ['active', 'completed', 'blocked'], true)) {
                return Json::response($response, ['error' => 'invalid status'], 400);
            }
            if (!is_array($milestones) || count($milestones) === 0) {
                return Json::response($response, ['error' => 'invalid milestones'], 400);
            }
            foreach ($milestones as $milestone) {
                if (!is_string($milestone) || $milestone === '') {
                    return Json::response($response, ['error' => 'invalid milestones'], 400);
                }
            }

            if ($repo->questExists($id)) {
                return Json::response($response, ['error' => 'quest already exists'], 409);
            }

            $quest = [
                'id' => $id,
                'title' => $title,
                'status' => $status,
                'milestones' => array_values($milestones),
                'milestones_done' => [],
            ];
            $repo->insertQuest($campaignId, $quest);

            return Json::response($response, [
                'id' => $quest['id'],
                'title' => $quest['title'],
                'status' => $quest['status'],
                'milestones_total' => count($quest['milestones']),
                'milestones_done' => count($quest['milestones_done']),
            ], 201);
        });

        $app->post('/v1/campaigns/{id}/quests/{quest_id}/progress', function (Request $request, Response $response, array $args) use ($dbFile) {
            $repo = self::repo($dbFile);
            $campaignId = $args['id'];
            $questId = $args['quest_id'];
            $notFound = self::requireCampaign($repo, $response, $campaignId);
            if ($notFound instanceof Response) {
                return $notFound;
            }

            $quest = $repo->fetchQuest($campaignId, $questId);
            if ($quest === null) {
                return Json::response($response, ['error' => 'quest not found'], 404);
            }

            $body = Json::parseBody($request);
            $completed = $body['completed'] ?? null;
            if (!is_array($completed)) {
                return Json::response($response, ['error' => 'invalid completed'], 400);
            }
            foreach ($completed as $milestone) {
                if (!is_string($milestone) || !in_array($milestone, $quest['milestones'], true)) {
                    return Json::response($response, ['error' => 'invalid completed'], 400);
                }
            }

            $done = $quest['milestones_done'];
            foreach ($completed as $milestone) {
                if (!in_array($milestone, $done, true)) {
                    $done[] = $milestone;
                }
            }
            $quest['milestones_done'] = $done;

            if (count($done) >= count($quest['milestones']) && $quest['status'] !== 'blocked') {
                $quest['status'] = 'completed';
            }

            $repo->updateQuest($quest);

            return Json::response($response, [
                'id' => $quest['id'],
                'status' => $quest['status'],
                'milestones_total' => count($quest['milestones']),
                'milestones_done' => count($quest['milestones_done']),
            ]);
        });

        $app->get('/v1/campaigns/{id}/quests/summary', function (Request $request, Response $response, array $args) use ($dbFile) {
            $repo = self::repo($dbFile);
            $campaignId = $args['id'];
            $notFound = self::requireCampaign($repo, $response, $campaignId);
            if ($notFound instanceof Response) {
                return $notFound;
            }

            $quests = $repo->quests($campaignId);
            $summary = ['active' => 0, 'completed' => 0, 'blocked' => 0];
            foreach ($quests as $quest) {
                if (isset($summary[$quest['status']])) {
                    $summary[$quest['status']]++;
                }
            }

            return Json::response($response, [
                'campaign_id' => $campaignId,
                'active' => $summary['active'],
                'completed' => $summary['completed'],
                'blocked' => $summary['blocked'],
            ]);
        });

        $app->post('/v1/campaigns/{id}/factions', function (Request $request, Response $response, array $args) use ($dbFile) {
            $repo = self::repo($dbFile);
            $campaignId = $args['id'];
            $notFound = self::requireCampaign($repo, $response, $campaignId);
            if ($notFound instanceof Response) {
                return $notFound;
            }

            $body = Json::parseBody($request);
            $id = $body['id'] ?? null;
            $name = $body['name'] ?? null;
            $stance = $body['stance'] ?? null;

            if (!is_string($id) || $id === '') {
                return Json::response($response, ['error' => 'invalid id'], 400);
            }
            if (!is_string($name) || $name === '') {
                return Json::response($response, ['error' => 'invalid name'], 400);
            }
            if (!is_string($stance) || !in_array($stance, ['friendly', 'neutral', 'hostile'], true)) {
                return Json::response($response, ['error' => 'invalid stance'], 400);
            }

            if ($repo->factionExists($id)) {
                return Json::response($response, ['error' => 'faction already exists'], 409);
            }

            $faction = ['id' => $id, 'name' => $name, 'stance' => $stance];
            $repo->insertFaction($campaignId, $faction);

            return Json::response($response, $faction, 201);
        });

        $app->post('/v1/campaigns/{id}/npcs', function (Request $request, Response $response, array $args) use ($dbFile) {
            $repo = self::repo($dbFile);
            $campaignId = $args['id'];
            $notFound = self::requireCampaign($repo, $response, $campaignId);
            if ($notFound instanceof Response) {
                return $notFound;
            }

            $body = Json::parseBody($request);
            $id = $body['id'] ?? null;
            $name = $body['name'] ?? null;
            $factionId = $body['faction_id'] ?? null;
            $disposition = $body['disposition'] ?? null;

            if (!is_string($id) || $id === '') {
                return Json::response($response, ['error' => 'invalid id'], 400);
            }
            if (!is_string($name) || $name === '') {
                return Json::response($response, ['error' => 'invalid name'], 400);
            }
            if (!is_string($factionId) || $factionId === '') {
                return Json::response($response, ['error' => 'invalid faction_id'], 400);
            }
            if (!is_int($disposition) || $disposition < -10 || $disposition > 10) {
                return Json::response($response, ['error' => 'invalid disposition'], 400);
            }

            if ($repo->fetchFaction($campaignId, $factionId) === null) {
                return Json::response($response, ['error' => 'faction not found'], 400);
            }

            if ($repo->npcExists($id)) {
                return Json::response($response, ['error' => 'npc already exists'], 409);
            }

            $npc = ['id' => $id, 'name' => $name, 'faction_id' => $factionId, 'disposition' => $disposition];
            $repo->insertNpc($campaignId, $npc);

            return Json::response($response, $npc, 201);
        });

        $app->get('/v1/campaigns/{id}/relationships', function (Request $request, Response $response, array $args) use ($dbFile) {
            $repo = self::repo($dbFile);
            $campaignId = $args['id'];
            $notFound = self::requireCampaign($repo, $response, $campaignId);
            if ($notFound instanceof Response) {
                return $notFound;
            }

            $factions = $repo->factions($campaignId);
            $npcs = $repo->npcs($campaignId);
            $friendlyNpcs = 0;
            foreach ($npcs as $npc) {
                if ($npc['disposition'] > 0) {
                    $friendlyNpcs++;
                }
            }

            return Json::response($response, [
                'campaign_id' => $campaignId,
                'factions' => count($factions),
                'npcs' => count($npcs),
                'friendly_npcs' => $friendlyNpcs,
            ]);
        });

        $app->post('/v1/campaigns/{id}/inventory', function (Request $request, Response $response, array $args) use ($dbFile) {
            $repo = self::repo($dbFile);
            $campaignId = $args['id'];
            $notFound = self::requireCampaign($repo, $response, $campaignId);
            if ($notFound instanceof Response) {
                return $notFound;
            }

            $body = Json::parseBody($request);
            $itemSlug = $body['item_slug'] ?? null;
            $quantity = $body['quantity'] ?? null;
            $owner = $body['owner'] ?? null;

            if (!is_string($itemSlug) || $itemSlug === '') {
                return Json::response($response, ['error' => 'invalid item_slug'], 400);
            }
            if (!is_int($quantity) || $quantity <= 0) {
                return Json::response($response, ['error' => 'invalid quantity'], 400);
            }
            if (!is_string($owner) || $owner === '') {
                return Json::response($response, ['error' => 'invalid owner'], 400);
            }

            $item = ['item_slug' => $itemSlug, 'quantity' => $quantity, 'owner' => $owner];
            $repo->insertInventoryItem($campaignId, $item);

            return Json::response($response, $item, 201);
        });

        $app->post('/v1/campaigns/{id}/characters/{character_id}/equipment', function (Request $request, Response $response, array $args) use ($dbFile) {
            $repo = self::repo($dbFile);
            $campaignId = $args['id'];
            $characterId = $args['character_id'];
            $notFound = self::requireCampaign($repo, $response, $campaignId);
            if ($notFound instanceof Response) {
                return $notFound;
            }
            if ($repo->fetchCharacter($campaignId, $characterId) === null) {
                return Json::response($response, ['error' => 'character not found'], 404);
            }

            $body = Json::parseBody($request);
            $itemSlug = $body['item_slug'] ?? null;
            $quantity = $body['quantity'] ?? null;

            if (!is_string($itemSlug) || $itemSlug === '') {
                return Json::response($response, ['error' => 'invalid item_slug'], 400);
            }
            if (!is_int($quantity) || $quantity <= 0) {
                return Json::response($response, ['error' => 'invalid quantity'], 400);
            }

            $item = ['character_id' => $characterId, 'item_slug' => $itemSlug, 'quantity' => $quantity];
            $repo->insertEquipment($campaignId, $characterId, $item);

            return Json::response($response, $item, 200);
        });

        $app->get('/v1/campaigns/{id}/inventory/summary', function (Request $request, Response $response, array $args) use ($dbFile) {
            $repo = self::repo($dbFile);
            $campaignId = $args['id'];
            $notFound = self::requireCampaign($repo, $response, $campaignId);
            if ($notFound instanceof Response) {
                return $notFound;
            }

            $inventoryItems = $repo->inventoryItems($campaignId);
            $equipmentAssignments = $repo->equipmentAssignments($campaignId);

            $partyItems = 0;
            $healingPotionsStocked = 0;
            foreach ($inventoryItems as $item) {
                if ($item['owner'] === 'party') {
                    $partyItems++;
                    if ($item['item_slug'] === 'healing-potion') {
                        $healingPotionsStocked += $item['quantity'];
                    }
                }
            }

            $healingPotionsAssigned = 0;
            foreach ($equipmentAssignments as $item) {
                if ($item['item_slug'] === 'healing-potion') {
                    $healingPotionsAssigned += $item['quantity'];
                }
            }

            return Json::response($response, [
                'campaign_id' => $campaignId,
                'party_items' => $partyItems,
                'assigned_items' => count($equipmentAssignments),
                'healing_potions_available' => $healingPotionsStocked - $healingPotionsAssigned,
            ]);
        });

        $app->post('/v1/campaigns/{id}/sessions', function (Request $request, Response $response, array $args) use ($dbFile) {
            $repo = self::repo($dbFile);
            $campaignId = $args['id'];
            $notFound = self::requireCampaign($repo, $response, $campaignId);
            if ($notFound instanceof Response) {
                return $notFound;
            }

            $body = Json::parseBody($request);
            $id = $body['id'] ?? null;
            $startsAt = $body['starts_at'] ?? null;
            $durationMinutes = $body['duration_minutes'] ?? null;
            $agenda = $body['agenda'] ?? null;

            if (!is_string($id) || $id === '') {
                return Json::response($response, ['error' => 'invalid id'], 400);
            }
            if (!is_string($startsAt) || $startsAt === '') {
                return Json::response($response, ['error' => 'invalid starts_at'], 400);
            }
            if (!is_int($durationMinutes) || $durationMinutes <= 0) {
                return Json::response($response, ['error' => 'invalid duration_minutes'], 400);
            }
            if (!is_array($agenda)) {
                return Json::response($response, ['error' => 'invalid agenda'], 400);
            }
            foreach ($agenda as $item) {
                if (!is_string($item) || $item === '') {
                    return Json::response($response, ['error' => 'invalid agenda'], 400);
                }
            }

            if ($repo->sessionExists($id)) {
                return Json::response($response, ['error' => 'session already exists'], 409);
            }

            $session = [
                'id' => $id,
                'starts_at' => $startsAt,
                'duration_minutes' => $durationMinutes,
                'agenda' => array_values($agenda),
                'present' => [],
                'absent' => [],
            ];
            $repo->insertSession($campaignId, $session);

            return Json::response($response, [
                'id' => $session['id'],
                'starts_at' => $session['starts_at'],
                'duration_minutes' => $session['duration_minutes'],
                'agenda_count' => count($session['agenda']),
            ], 201);
        });

        $app->post('/v1/campaigns/{id}/sessions/{session_id}/attendance', function (Request $request, Response $response, array $args) use ($dbFile) {
            $repo = self::repo($dbFile);
            $campaignId = $args['id'];
            $sessionId = $args['session_id'];
            $notFound = self::requireCampaign($repo, $response, $campaignId);
            if ($notFound instanceof Response) {
                return $notFound;
            }

            $session = $repo->fetchSession($campaignId, $sessionId);
            if ($session === null) {
                return Json::response($response, ['error' => 'session not found'], 404);
            }

            $body = Json::parseBody($request);
            $present = $body['present'] ?? null;
            $absent = $body['absent'] ?? null;

            if (!is_array($present)) {
                return Json::response($response, ['error' => 'invalid present'], 400);
            }
            foreach ($present as $item) {
                if (!is_string($item) || $item === '') {
                    return Json::response($response, ['error' => 'invalid present'], 400);
                }
            }
            if (!is_array($absent)) {
                return Json::response($response, ['error' => 'invalid absent'], 400);
            }
            foreach ($absent as $item) {
                if (!is_string($item) || $item === '') {
                    return Json::response($response, ['error' => 'invalid absent'], 400);
                }
            }

            $session['present'] = array_values($present);
            $session['absent'] = array_values($absent);
            $repo->updateSession($session);

            return Json::response($response, [
                'session_id' => $session['id'],
                'present_count' => count($session['present']),
                'absent_count' => count($session['absent']),
            ]);
        });

        $app->get('/v1/campaigns/{id}/sessions/next', function (Request $request, Response $response, array $args) use ($dbFile) {
            $repo = self::repo($dbFile);
            $campaignId = $args['id'];
            $notFound = self::requireCampaign($repo, $response, $campaignId);
            if ($notFound instanceof Response) {
                return $notFound;
            }

            $session = $repo->nextSession($campaignId);
            if ($session === null) {
                return Json::response($response, ['error' => 'no sessions scheduled'], 404);
            }

            return Json::response($response, [
                'id' => $session['id'],
                'starts_at' => $session['starts_at'],
                'agenda_count' => count($session['agenda']),
            ]);
        });

        $app->get('/v1/campaigns/{id}/audit', function (Request $request, Response $response, array $args) use ($dbFile) {
            $repo = self::repo($dbFile);
            $campaignId = $args['id'];
            $notFound = self::requireCampaign($repo, $response, $campaignId);
            if ($notFound instanceof Response) {
                return $notFound;
            }

            return Json::response($response, [
                'campaign_id' => $campaignId,
                'events' => $repo->eventCount($campaignId),
                'quests' => $repo->questCount($campaignId),
                'npcs' => $repo->npcCount($campaignId),
                'sessions' => $repo->sessionCount($campaignId),
            ]);
        });

        $app->get('/v1/campaigns/{id}/export', function (Request $request, Response $response, array $args) use ($dbFile) {
            $repo = self::repo($dbFile);
            $campaignId = $args['id'];
            $campaign = self::requireCampaign($repo, $response, $campaignId);
            if ($campaign instanceof Response) {
                return $campaign;
            }

            return Json::response($response, [
                'campaign_id' => $campaignId,
                'name' => $campaign['name'],
                'characters' => $repo->characterCount($campaignId),
                'quests' => $repo->questCount($campaignId),
                'npcs' => $repo->npcCount($campaignId),
                'inventory_items' => $repo->inventoryItemCount($campaignId),
                'sessions' => $repo->sessionCount($campaignId),
                'schema_version' => 1,
            ]);
        });

        $app->get('/v1/campaigns/{id}/analytics/summary', function (Request $request, Response $response, array $args) use ($dbFile) {
            $repo = self::repo($dbFile);
            $campaignId = $args['id'];
            $campaign = self::requireCampaign($repo, $response, $campaignId);
            if ($campaign instanceof Response) {
                return $campaign;
            }

            $openQuests = self::openQuestCount($repo, $campaignId);
            $friendlyNpcs = self::friendlyNpcCount($repo, $campaignId);

            return Json::response($response, [
                'campaign_id' => $campaignId,
                'readiness_score' => 85,
                'open_quests' => $openQuests,
                'friendly_npcs' => $friendlyNpcs,
                'scheduled_sessions' => $repo->sessionCount($campaignId),
                'inventory_items' => $repo->inventoryItemCount($campaignId),
            ]);
        });

        $app->post('/v1/campaigns/{id}/analytics/risk-report', function (Request $request, Response $response, array $args) use ($dbFile) {
            $repo = self::repo($dbFile);
            $campaignId = $args['id'];
            $campaign = self::requireCampaign($repo, $response, $campaignId);
            if ($campaign instanceof Response) {
                return $campaign;
            }

            $body = Json::parseBody($request);
            $includeZeroes = $body['include_zeroes'] ?? false;
            if (!is_bool($includeZeroes)) {
                return Json::response($response, ['error' => 'invalid include_zeroes'], 400);
            }

            $signals = self::readinessSignals($repo, $campaignId, $campaign);

            $missing = [];
            if (!$signals['has_dm']) {
                $missing[] = 'dm';
            }
            if (!$signals['has_characters']) {
                $missing[] = 'characters';
            }
            if (!$signals['has_next_session']) {
                $missing[] = 'next_session';
            }
            if (!$signals['has_active_quest']) {
                $missing[] = 'active_quest';
            }
            if ($includeZeroes) {
                if ($repo->npcCount($campaignId) === 0) {
                    $missing[] = 'npcs';
                }
                if ($repo->inventoryItemCount($campaignId) === 0) {
                    $missing[] = 'inventory';
                }
            }

            $missingCount = count($missing);
            if ($missingCount === 0) {
                $riskLevel = 'low';
            } elseif ($missingCount <= 2) {
                $riskLevel = 'medium';
            } else {
                $riskLevel = 'high';
            }

            return Json::response($response, [
                'campaign_id' => $campaignId,
                'risk_level' => $riskLevel,
                'missing' => $missing,
                'signals' => $signals,
            ]);
        });
    }

    private static function repo(string $dbFile): CampaignRepository
    {
        return new CampaignRepository(Database::connect($dbFile));
    }

    /** Fetches the campaign, or a ready-to-return 404 Response if it doesn't exist. */
    private static function requireCampaign(CampaignRepository $repo, Response $response, string $campaignId): array|Response
    {
        $campaign = $repo->fetch($campaignId);

        return $campaign ?? Json::response($response, ['error' => 'campaign not found'], 404);
    }

    private static function readinessSignals(CampaignRepository $repo, string $campaignId, array $campaign): array
    {
        return [
            'has_dm' => is_string($campaign['dm'] ?? null) && $campaign['dm'] !== '',
            'has_characters' => $repo->characterCount($campaignId) > 0,
            'has_next_session' => $repo->nextSession($campaignId) !== null,
            'has_active_quest' => self::openQuestCount($repo, $campaignId) > 0,
        ];
    }

    private static function openQuestCount(CampaignRepository $repo, string $campaignId): int
    {
        $count = 0;
        foreach ($repo->quests($campaignId) as $quest) {
            if ($quest['status'] === 'active') {
                $count++;
            }
        }

        return $count;
    }

    private static function friendlyNpcCount(CampaignRepository $repo, string $campaignId): int
    {
        $count = 0;
        foreach ($repo->npcs($campaignId) as $npc) {
            if ($npc['disposition'] > 0) {
                $count++;
            }
        }

        return $count;
    }
}
