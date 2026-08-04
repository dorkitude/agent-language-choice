<?php

declare(strict_types=1);

namespace App\Routes;

use App\Http\Auth;
use App\Http\Json;
use App\Rules\Characters;
use App\Rules\Spells;
use App\Rules\Validation;
use App\Storage\Database;
use App\Storage\PlayCampaignRepository;
use App\Storage\UserRepository;
use Psr\Http\Message\ResponseInterface as Response;
use Psr\Http\Message\ServerRequestInterface as Request;
use Slim\App;

/** Protected campaign-play surface under /v1/play, gated on a `Bearer session-<username>` actor. */
final class PlayRoutes
{
    /** Logical (turn-based, not wall-clock) window added to turn_number to form the deadline. */
    private const TURN_DEADLINE_WINDOW = 1;

    /** Nudge count at which a turn is considered overdue. */
    private const NUDGE_OVERDUE_THRESHOLD = 3;

    /** Default max hit points assigned to a party member on joining. */
    private const DEFAULT_HP_MAX = 20;

    /** Default gold balance assigned to a party member on joining. */
    private const DEFAULT_GOLD = 10;

    public static function register(App $app, string $dbFile): void
    {
        $app->post('/v1/play/campaigns', function (Request $request, Response $response) use ($dbFile) {
            $campaigns = self::repo($dbFile);

            $actor = self::requireActor($request, $response);
            if ($actor instanceof Response) {
                return $actor;
            }
            if ($actor['role'] !== 'dm') {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $body = Json::parseBody($request);
            $id = $body['id'] ?? null;
            $name = $body['name'] ?? null;
            $maxPlayers = $body['max_players'] ?? null;

            if (!is_string($id) || $id === '') {
                return Json::response($response, ['error' => 'invalid id'], 400);
            }
            if (!is_string($name) || $name === '') {
                return Json::response($response, ['error' => 'invalid name'], 400);
            }
            if (!is_int($maxPlayers) || $maxPlayers < 1) {
                return Json::response($response, ['error' => 'invalid max_players'], 400);
            }

            if ($campaigns->fetch($id) !== null) {
                return Json::response($response, ['error' => 'campaign already exists'], 409);
            }

            $campaign = [
                'id' => $id,
                'name' => $name,
                'owner' => $actor['username'],
                'status' => 'lobby',
                'max_players' => $maxPlayers,
            ];

            $campaigns->insert($campaign);

            return Json::response($response, $campaign, 201);
        });

        $app->post('/v1/play/campaigns/{id}/members', function (Request $request, Response $response, array $args) use ($dbFile) {
            $campaigns = self::repo($dbFile);

            $actor = self::requireActor($request, $response);
            if ($actor instanceof Response) {
                return $actor;
            }
            if ($actor['role'] !== 'player') {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $campaignId = $args['id'];
            $campaign = self::requireCampaign($campaigns, $response, $campaignId);
            if ($campaign instanceof Response) {
                return $campaign;
            }

            $body = Json::parseBody($request);
            $characterId = $body['character_id'] ?? null;
            $name = $body['name'] ?? null;
            $class = $body['class'] ?? null;

            if (!is_string($characterId) || $characterId === '') {
                return Json::response($response, ['error' => 'invalid character_id'], 400);
            }
            if (!is_string($name) || $name === '') {
                return Json::response($response, ['error' => 'invalid name'], 400);
            }
            if (!is_string($class) || $class === '') {
                return Json::response($response, ['error' => 'invalid class'], 400);
            }

            if ($campaigns->memberByUsername($campaignId, $actor['username']) !== null) {
                return Json::response($response, ['error' => 'already a member'], 409);
            }
            if ($campaigns->characterIdExists($campaignId, $characterId)) {
                return Json::response($response, ['error' => 'character already exists'], 409);
            }
            if ($campaigns->memberCount($campaignId) >= $campaign['max_players']) {
                return Json::response($response, ['error' => 'party full'], 409);
            }

            $member = [
                'username' => $actor['username'],
                'character_id' => $characterId,
                'name' => $name,
                'class' => $class,
                'hp_current' => self::DEFAULT_HP_MAX,
                'hp_max' => self::DEFAULT_HP_MAX,
                'status' => 'alive',
                'death_save_successes' => 0,
                'death_save_failures' => 0,
                'owner' => $actor['username'],
                'gold' => self::DEFAULT_GOLD,
            ];
            $campaigns->insertMember($campaignId, $actor['username'], $characterId, $member);

            return Json::response($response, $member, 201);
        });

        $app->post('/v1/play/campaigns/{id}/start', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;
            $campaignId = $args['id'];

            if (!self::isOwningDm($actor, $campaign)) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            if ($campaign['status'] !== 'lobby' || $campaigns->memberCount($campaignId) < 2) {
                return Json::response($response, ['error' => 'campaign cannot be started'], 409);
            }

            $firstMember = $campaigns->firstMember($campaignId);

            $campaign['status'] = 'active';
            $campaign['current_actor'] = $firstMember['username'];
            $campaign['turn_number'] = 1;

            $campaigns->update($campaign);

            return Json::response($response, [
                'id' => $campaign['id'],
                'status' => $campaign['status'],
                'current_actor' => $campaign['current_actor'],
                'turn_number' => $campaign['turn_number'],
            ], 200);
        });

        $app->post('/v1/play/campaigns/{id}/narrations', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;
            $campaignId = $args['id'];

            if (!self::isOwningDm($actor, $campaign) && !self::hasActiveDelegatePower($campaign, $actor['username'], 'narrate')) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $body = Json::parseBody($request);
            $text = $body['text'] ?? null;

            if (!is_string($text) || $text === '') {
                return Json::response($response, ['error' => 'invalid text'], 400);
            }

            $sequence = $campaigns->nextEventSequence($campaignId);
            $event = [
                'sequence' => $sequence,
                'kind' => 'narration',
                'actor' => self::isOwningDm($actor, $campaign) ? 'dm' : $actor['username'],
                'text' => $text,
            ];
            $campaigns->insertEvent($campaignId, $sequence, $event);

            return Json::response($response, $event, 201);
        });

        $app->post('/v1/play/campaigns/{id}/actions', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;
            $campaignId = $args['id'];

            $isOwner = $campaign['owner'] === $actor['username'];
            $member = $campaigns->memberByUsername($campaignId, $actor['username']);
            if (!$isOwner && $member === null) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            if ($isOwner || $campaign['current_actor'] !== $actor['username']) {
                return Json::response($response, ['error' => 'not your turn'], 409);
            }

            $body = Json::parseBody($request);
            $type = $body['type'] ?? null;
            $text = $body['text'] ?? null;

            if (!is_string($type) || $type === '') {
                return Json::response($response, ['error' => 'invalid type'], 400);
            }
            if (!is_string($text) || $text === '') {
                return Json::response($response, ['error' => 'invalid text'], 400);
            }

            $sequence = $campaigns->nextEventSequence($campaignId);
            $event = [
                'sequence' => $sequence,
                'kind' => 'action',
                'actor' => $actor['username'],
                'type' => $type,
                'text' => $text,
            ];
            $campaigns->insertEvent($campaignId, $sequence, $event);

            $campaign['current_actor'] = $campaign['owner'];
            $campaigns->update($campaign);

            $event['next_actor'] = 'dm';

            return Json::response($response, $event, 201);
        });

        $app->post('/v1/play/campaigns/{id}/resolutions', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;
            $campaignId = $args['id'];

            $isOwner = $campaign['owner'] === $actor['username'];
            $member = $campaigns->memberByUsername($campaignId, $actor['username']);
            if (!$isOwner && $member === null) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            if (!$isOwner || $campaign['current_actor'] !== $campaign['owner']) {
                return Json::response($response, ['error' => 'not the DM turn'], 409);
            }

            $body = Json::parseBody($request);
            $text = $body['text'] ?? null;

            if (!is_string($text) || $text === '') {
                return Json::response($response, ['error' => 'invalid text'], 400);
            }

            // Two-player rotation: after the first pair of turns (turn 1), hand off to the
            // second joiner; from turn 2 onward, alternate back to the first joiner.
            $order = $campaigns->membersInJoinOrder($campaignId);
            $next = $order[1]['username'];
            if (($campaign['turn_number'] ?? 0) >= 2) {
                $next = $order[0]['username'];
            }

            $sequence = $campaigns->nextEventSequence($campaignId);
            $event = [
                'sequence' => $sequence,
                'kind' => 'resolution',
                'actor' => 'dm',
                'text' => $text,
            ];
            $campaigns->insertEvent($campaignId, $sequence, $event);

            $campaign['current_actor'] = $next;
            $campaign['turn_number'] = ($campaign['turn_number'] ?? 1) + 1;
            $campaigns->update($campaign);

            $event['next_actor'] = $campaign['current_actor'];
            $event['turn_number'] = $campaign['turn_number'];

            return Json::response($response, $event, 201);
        });

        $app->get('/v1/play/campaigns/{id}/turn', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;
            $campaignId = $args['id'];

            $isOwner = $campaign['owner'] === $actor['username'];
            $isMember = $campaigns->memberByUsername($campaignId, $actor['username']) !== null;
            if (!$isOwner && !$isMember) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $phase = ($campaign['current_actor'] ?? null) === $campaign['owner'] ? 'dm' : 'player';

            $queue = [];
            foreach ($campaigns->membersInJoinOrder($campaignId) as $member) {
                $queue[] = $member['username'];
                $queue[] = $campaign['owner'];
            }

            $nudgeCount = $campaign['nudge_count'] ?? 0;
            $turnNumber = $campaign['turn_number'] ?? 1;

            return Json::response($response, [
                'campaign_id' => $campaign['id'],
                'current_actor' => $campaign['current_actor'] ?? null,
                'phase' => $phase,
                'turn_number' => $campaign['turn_number'] ?? null,
                'queue' => $queue,
                'overdue' => $nudgeCount >= self::NUDGE_OVERDUE_THRESHOLD,
                'logical_deadline' => $turnNumber + self::TURN_DEADLINE_WINDOW,
                'nudge_count' => $nudgeCount,
            ], 200);
        });

        $app->post('/v1/play/campaigns/{id}/turn/nudge', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;
            $campaignId = $args['id'];

            if (!self::isOwningDm($actor, $campaign)) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $body = Json::parseBody($request);
            $message = $body['message'] ?? null;

            if (!is_string($message) || $message === '') {
                return Json::response($response, ['error' => 'invalid message'], 400);
            }

            $nudgeCount = ($campaign['nudge_count'] ?? 0) + 1;
            $campaign['nudge_count'] = $nudgeCount;
            $campaigns->update($campaign);

            $sequence = $campaigns->nextEventSequence($campaignId);
            $campaigns->insertEvent($campaignId, $sequence, [
                'sequence' => $sequence,
                'kind' => 'nudge',
                'actor' => $actor['username'],
                'text' => $message,
            ]);

            return Json::response($response, [
                'campaign_id' => $campaign['id'],
                'actor' => $actor['username'],
                'current_actor' => $campaign['current_actor'] ?? null,
                'target' => $campaign['current_actor'] ?? null,
                'message' => $message,
                'nudge_count' => $nudgeCount,
            ], 201);
        });

        $app->get('/v1/play/campaigns/{id}/my-turn', function (Request $request, Response $response, array $args) use ($dbFile) {
            $campaigns = self::repo($dbFile);

            $actor = self::requireActor($request, $response);
            if ($actor instanceof Response) {
                return $actor;
            }
            if ($actor['role'] !== 'player') {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $campaignId = $args['id'];
            $campaign = self::requireCampaign($campaigns, $response, $campaignId);
            if ($campaign instanceof Response) {
                return $campaign;
            }

            $member = $campaigns->memberByUsername($campaignId, $actor['username']);
            if ($member === null) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $currentActor = $campaign['current_actor'] ?? null;

            return Json::response($response, [
                'campaign_id' => $campaign['id'],
                'is_my_turn' => $currentActor !== null && $currentActor === $actor['username'],
                'current_actor' => $currentActor,
                'character' => [
                    'id' => $member['character_id'],
                    'name' => $member['name'],
                ],
                'recent_events' => $campaigns->recentEvents($campaignId, 10),
            ], 200);
        });

        $app->get('/v1/play/campaigns/{id}/gm/status', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;
            $campaignId = $args['id'];

            if (!self::isOwningDm($actor, $campaign)) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $currentActor = $campaign['current_actor'] ?? null;

            $party = array_map(
                static fn (array $member) => [
                    'username' => $member['username'],
                    'character_id' => $member['character_id'],
                    'name' => $member['name'],
                    'class' => $member['class'],
                ],
                $campaigns->membersInJoinOrder($campaignId)
            );

            return Json::response($response, [
                'campaign_id' => $campaign['id'],
                'needs_attention' => $currentActor !== null && $currentActor === $campaign['owner'],
                'current_actor' => $currentActor,
                'party' => $party,
                'recent_events' => $campaigns->recentEvents($campaignId, 10),
            ], 200);
        });

        $app->put('/v1/play/campaigns/{id}/document', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;
            $campaignId = $args['id'];

            if (!self::isOwningDm($actor, $campaign)) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $body = Json::parseBody($request);
            $story = $body['story'] ?? null;
            $dmNotes = $body['dm_notes'] ?? null;

            if (!is_string($story) || $story === '') {
                return Json::response($response, ['error' => 'invalid story'], 400);
            }
            if (!is_string($dmNotes)) {
                return Json::response($response, ['error' => 'invalid dm_notes'], 400);
            }

            $campaign['document'] = [
                'story' => $story,
                'dm_notes' => $dmNotes,
            ];
            $campaigns->update($campaign);

            return Json::response($response, [
                'campaign_id' => $campaign['id'],
                'story' => $story,
                'dm_notes' => $dmNotes,
            ], 200);
        });

        $app->get('/v1/play/campaigns/{id}/document', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;
            $campaignId = $args['id'];

            $isOwner = $campaign['owner'] === $actor['username'];
            $isMember = $campaigns->memberByUsername($campaignId, $actor['username']) !== null;
            if (!$isOwner && !$isMember) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            // DM notes are private to the owning DM; players only ever see the story.
            $document = $campaign['document'] ?? ['story' => '', 'dm_notes' => ''];

            $result = [
                'campaign_id' => $campaign['id'],
                'story' => $document['story'] ?? '',
            ];
            if ($isOwner) {
                $result['dm_notes'] = $document['dm_notes'] ?? '';
            }

            return Json::response($response, $result, 200);
        });
        $app->put('/v1/play/campaigns/{id}/session-zero', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;

            if (!self::isOwningDm($actor, $campaign)) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            if ($campaign['status'] !== 'lobby') {
                return Json::response($response, ['error' => 'campaign already started'], 409);
            }

            $body = Json::parseBody($request);
            $rules = $body['rules'] ?? null;
            $tone = $body['tone'] ?? null;
            $consent = $body['consent'] ?? null;

            if (!is_string($rules) || $rules === '') {
                return Json::response($response, ['error' => 'invalid rules'], 400);
            }
            if (!is_string($tone) || $tone === '') {
                return Json::response($response, ['error' => 'invalid tone'], 400);
            }
            if (!is_array($consent) || !array_is_list($consent) || count($consent) === 0) {
                return Json::response($response, ['error' => 'invalid consent'], 400);
            }
            foreach ($consent as $item) {
                if (!is_string($item) || $item === '') {
                    return Json::response($response, ['error' => 'invalid consent'], 400);
                }
            }
            if (count($consent) !== count(array_unique($consent))) {
                return Json::response($response, ['error' => 'invalid consent'], 400);
            }

            $sessionZero = [
                'rules' => $rules,
                'tone' => $tone,
                'consent' => array_values($consent),
            ];

            $campaign['session_zero'] = $sessionZero;
            $campaigns->update($campaign);

            return Json::response($response, $sessionZero, 200);
        });
        $app->get('/v1/play/campaigns/{id}/session-zero', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;
            $campaignId = $args['id'];

            $isOwner = $campaign['owner'] === $actor['username'];
            $isMember = $campaigns->memberByUsername($campaignId, $actor['username']) !== null;
            if (!$isOwner && !$isMember) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $sessionZero = $campaign['session_zero'] ?? null;
            if ($sessionZero === null) {
                return Json::response($response, ['error' => 'session-zero settings not found'], 404);
            }

            return Json::response($response, $sessionZero, 200);
        });
        $app->post('/v1/play/campaigns/{id}/scenes', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;
            $campaignId = $args['id'];

            if (!self::isOwningDm($actor, $campaign)) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $body = Json::parseBody($request);
            $sceneId = $body['id'] ?? null;
            $name = $body['name'] ?? null;

            if (!is_string($sceneId) || $sceneId === '') {
                return Json::response($response, ['error' => 'invalid id'], 400);
            }
            if (!is_string($name) || $name === '') {
                return Json::response($response, ['error' => 'invalid name'], 400);
            }

            $scenes = $campaign['scenes'] ?? [];
            if (isset($scenes[$sceneId])) {
                return Json::response($response, ['error' => 'scene already exists'], 409);
            }

            $scene = [
                'id' => $sceneId,
                'name' => $name,
                'status' => 'open',
            ];
            $scenes[$sceneId] = $scene;
            $campaign['scenes'] = $scenes;
            $campaigns->update($campaign);

            return Json::response($response, $scene, 201);
        });

        $app->post('/v1/play/campaigns/{id}/scenes/{scene_id}/enter', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;
            $campaignId = $args['id'];

            if (!self::isOwningDm($actor, $campaign)) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $sceneId = $args['scene_id'];
            $scene = $campaign['scenes'][$sceneId] ?? null;
            if ($scene === null) {
                return Json::response($response, ['error' => 'scene not found'], 404);
            }
            if ($scene['status'] !== 'open') {
                return Json::response($response, ['error' => 'scene is closed'], 409);
            }

            $campaign['current_scene_id'] = $sceneId;
            $campaigns->update($campaign);

            $sequence = $campaigns->nextEventSequence($campaignId);
            $campaigns->insertEvent($campaignId, $sequence, [
                'sequence' => $sequence,
                'kind' => 'scene',
                'actor' => $actor['username'],
                'text' => $sceneId,
            ]);

            return Json::response($response, [
                'current_scene_id' => $sceneId,
                'name' => $scene['name'],
            ], 200);
        });

        $app->post('/v1/play/campaigns/{id}/scenes/{scene_id}/close', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;
            $campaignId = $args['id'];

            if (!self::isOwningDm($actor, $campaign)) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $sceneId = $args['scene_id'];
            $scene = $campaign['scenes'][$sceneId] ?? null;
            if ($scene === null) {
                return Json::response($response, ['error' => 'scene not found'], 404);
            }

            $scene['status'] = 'closed';
            $campaign['scenes'][$sceneId] = $scene;
            $campaigns->update($campaign);

            return Json::response($response, [
                'id' => $scene['id'],
                'status' => $scene['status'],
            ], 200);
        });

        $app->get('/v1/play/campaigns/{id}/scenes/current', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;
            $campaignId = $args['id'];

            $isOwner = $campaign['owner'] === $actor['username'];
            $isMember = $campaigns->memberByUsername($campaignId, $actor['username']) !== null;
            if (!$isOwner && !$isMember) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $sceneId = $campaign['current_scene_id'] ?? null;
            $scene = $sceneId !== null ? ($campaign['scenes'][$sceneId] ?? null) : null;
            if ($scene === null || $scene['status'] !== 'open') {
                return Json::response($response, ['error' => 'no current scene'], 404);
            }

            return Json::response($response, [
                'id' => $scene['id'],
                'name' => $scene['name'],
                'status' => $scene['status'],
            ], 200);
        });
        $app->post('/v1/play/campaigns/{id}/locations', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;
            $campaignId = $args['id'];

            if (!self::isOwningDm($actor, $campaign)) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $body = Json::parseBody($request);
            $locationId = $body['id'] ?? null;
            $name = $body['name'] ?? null;

            if (!is_string($locationId) || $locationId === '') {
                return Json::response($response, ['error' => 'invalid id'], 400);
            }
            if (!is_string($name) || $name === '') {
                return Json::response($response, ['error' => 'invalid name'], 400);
            }

            $locations = $campaign['locations'] ?? [];
            if (isset($locations[$locationId])) {
                return Json::response($response, ['error' => 'location already exists'], 409);
            }

            $location = [
                'id' => $locationId,
                'name' => $name,
                'connections' => [],
            ];
            $locations[$locationId] = $location;
            $campaign['locations'] = $locations;

            // The first location created becomes the party's starting location.
            if (!isset($campaign['current_location_id'])) {
                $campaign['current_location_id'] = $locationId;
            }

            $campaigns->update($campaign);

            return Json::response($response, [
                'id' => $location['id'],
                'name' => $location['name'],
            ], 201);
        });

        $app->post('/v1/play/campaigns/{id}/locations/{from_id}/connections', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;
            $campaignId = $args['id'];

            if (!self::isOwningDm($actor, $campaign)) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $fromId = $args['from_id'];
            $locations = $campaign['locations'] ?? [];
            $fromLocation = $locations[$fromId] ?? null;
            if ($fromLocation === null) {
                return Json::response($response, ['error' => 'location not found'], 404);
            }

            $body = Json::parseBody($request);
            $toId = $body['to_id'] ?? null;
            $travelTurns = $body['travel_turns'] ?? null;

            if (!is_string($toId) || $toId === '') {
                return Json::response($response, ['error' => 'invalid to_id'], 400);
            }
            if (!is_int($travelTurns) || $travelTurns < 1) {
                return Json::response($response, ['error' => 'invalid travel_turns'], 400);
            }
            if (!isset($locations[$toId])) {
                return Json::response($response, ['error' => 'destination not found'], 400);
            }

            foreach ($fromLocation['connections'] as $connection) {
                if ($connection['to_id'] === $toId) {
                    return Json::response($response, ['error' => 'already connected'], 400);
                }
            }

            $fromLocation['connections'][] = [
                'to_id' => $toId,
                'travel_turns' => $travelTurns,
            ];
            $locations[$fromId] = $fromLocation;
            $campaign['locations'] = $locations;
            $campaigns->update($campaign);

            return Json::response($response, [
                'from_id' => $fromId,
                'to_id' => $toId,
                'travel_turns' => $travelTurns,
            ], 201);
        });

        $app->get('/v1/play/campaigns/{id}/locations/{loc_id}/travel', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;
            $campaignId = $args['id'];

            $isOwner = $campaign['owner'] === $actor['username'];
            $isMember = $campaigns->memberByUsername($campaignId, $actor['username']) !== null;
            if (!$isOwner && !$isMember) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $locId = $args['loc_id'];
            $locations = $campaign['locations'] ?? [];
            $location = $locations[$locId] ?? null;
            if ($location === null) {
                return Json::response($response, ['error' => 'location not found'], 404);
            }

            $destinations = [];
            foreach ($location['connections'] as $connection) {
                $destination = $locations[$connection['to_id']] ?? null;
                if ($destination === null) {
                    continue;
                }
                $destinations[] = [
                    'id' => $destination['id'],
                    'name' => $destination['name'],
                    'travel_turns' => $connection['travel_turns'],
                ];
            }

            return Json::response($response, ['destinations' => $destinations], 200);
        });

        $app->post('/v1/play/campaigns/{id}/turn/travel', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;
            $campaignId = $args['id'];

            $isOwner = $campaign['owner'] === $actor['username'];
            $member = $campaigns->memberByUsername($campaignId, $actor['username']);
            if (!$isOwner && $member === null) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            if ($isOwner || $campaign['current_actor'] !== $actor['username']) {
                return Json::response($response, ['error' => 'not your turn'], 409);
            }

            $body = Json::parseBody($request);
            $destinationId = $body['destination_id'] ?? null;

            if (!is_string($destinationId) || $destinationId === '') {
                return Json::response($response, ['error' => 'invalid destination_id'], 400);
            }

            $locations = $campaign['locations'] ?? [];
            $currentLocationId = $campaign['current_location_id'] ?? null;
            $currentLocation = $currentLocationId !== null ? ($locations[$currentLocationId] ?? null) : null;

            $travelTurns = null;
            if ($currentLocation !== null) {
                foreach ($currentLocation['connections'] as $connection) {
                    if ($connection['to_id'] === $destinationId) {
                        $travelTurns = $connection['travel_turns'];
                        break;
                    }
                }
            }

            if ($travelTurns === null) {
                return Json::response($response, ['error' => 'invalid destination'], 409);
            }

            $sequence = $campaigns->nextEventSequence($campaignId);
            $event = [
                'sequence' => $sequence,
                'kind' => 'travel',
                'actor' => $actor['username'],
                'destination_id' => $destinationId,
                'travel_turns' => $travelTurns,
            ];
            $campaigns->insertEvent($campaignId, $sequence, $event);

            $campaign['current_location_id'] = $destinationId;
            $campaign['current_actor'] = $campaign['owner'];
            $campaigns->update($campaign);

            $event['next_actor'] = 'dm';

            return Json::response($response, $event, 201);
        });

        $app->post('/v1/play/campaigns/{id}/turn/rest', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;
            $campaignId = $args['id'];

            $isOwner = $campaign['owner'] === $actor['username'];
            $member = $campaigns->memberByUsername($campaignId, $actor['username']);
            if (!$isOwner && $member === null) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            if ($isOwner || $campaign['current_actor'] !== $actor['username']) {
                return Json::response($response, ['error' => 'not your turn'], 409);
            }

            $body = Json::parseBody($request);
            $type = $body['type'] ?? null;

            if ($type !== 'long' && $type !== 'short') {
                return Json::response($response, ['error' => 'invalid type'], 400);
            }

            if ($type === 'long') {
                $member['hp_current'] = $member['hp_max'];
                $campaigns->updateMember($campaignId, $actor['username'], $member);
            }

            $sequence = $campaigns->nextEventSequence($campaignId);
            $event = [
                'sequence' => $sequence,
                'kind' => 'rest',
                'actor' => $actor['username'],
                'type' => $type,
                'hp_current' => $member['hp_current'],
                'hp_max' => $member['hp_max'],
            ];
            $campaigns->insertEvent($campaignId, $sequence, $event);

            $campaign['current_actor'] = $campaign['owner'];
            $campaigns->update($campaign);

            $event['next_actor'] = 'dm';

            return Json::response($response, $event, 201);
        });

        $app->post('/v1/play/campaigns/{id}/encounters', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;
            $campaignId = $args['id'];

            if (!self::isOwningDm($actor, $campaign)) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $body = Json::parseBody($request);
            $encounterId = $body['id'] ?? null;
            $name = $body['name'] ?? null;

            if (!is_string($encounterId) || $encounterId === '') {
                return Json::response($response, ['error' => 'invalid id'], 400);
            }
            if (!is_string($name) || $name === '') {
                return Json::response($response, ['error' => 'invalid name'], 400);
            }

            $encounters = $campaign['encounters'] ?? [];
            if (isset($encounters[$encounterId])) {
                return Json::response($response, ['error' => 'encounter already exists'], 409);
            }

            foreach ($encounters as $existing) {
                if ($existing['status'] === 'active') {
                    return Json::response($response, ['error' => 'campaign already in combat'], 409);
                }
            }

            $encounter = [
                'id' => $encounterId,
                'name' => $name,
                'status' => 'active',
                'combatants' => [],
            ];
            $encounters[$encounterId] = $encounter;
            $campaign['encounters'] = $encounters;

            if (!($campaign['in_combat'] ?? false)) {
                $campaign['pre_combat_actor'] = $campaign['current_actor'] ?? null;
                $campaign['in_combat'] = true;
            }

            $campaigns->update($campaign);

            return Json::response($response, $encounter, 201);
        });

        $app->post('/v1/play/campaigns/{id}/encounters/{enc_id}/monsters', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;
            $campaignId = $args['id'];

            if (!self::isOwningDm($actor, $campaign)) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $encounterId = $args['enc_id'];
            $encounters = $campaign['encounters'] ?? [];
            if (!isset($encounters[$encounterId])) {
                return Json::response($response, ['error' => 'encounter not found'], 404);
            }

            $body = Json::parseBody($request);
            $monsterId = $body['monster_id'] ?? null;
            $name = $body['name'] ?? null;
            $hpMax = $body['hp_max'] ?? null;
            $initiative = $body['initiative'] ?? null;

            if (!is_string($monsterId) || $monsterId === '') {
                return Json::response($response, ['error' => 'invalid monster_id'], 400);
            }
            if (!is_string($name) || $name === '') {
                return Json::response($response, ['error' => 'invalid name'], 400);
            }
            if (!is_int($hpMax) || $hpMax <= 0) {
                return Json::response($response, ['error' => 'invalid hp_max'], 400);
            }
            if (!is_int($initiative)) {
                return Json::response($response, ['error' => 'invalid initiative'], 400);
            }

            $encounter = $encounters[$encounterId];
            $monsters = $encounter['monsters'] ?? [];
            if (isset($monsters[$monsterId])) {
                return Json::response($response, ['error' => 'monster already exists'], 409);
            }

            $monster = [
                'monster_id' => $monsterId,
                'name' => $name,
                'hp_max' => $hpMax,
                'initiative' => $initiative,
                'hp_current' => $hpMax,
            ];
            $monsters[$monsterId] = $monster;
            $encounter['monsters'] = $monsters;
            $encounters[$encounterId] = $encounter;
            $campaign['encounters'] = $encounters;
            $campaigns->update($campaign);

            return Json::response($response, $monster, 201);
        });

        $app->delete('/v1/play/campaigns/{id}/encounters/{enc_id}/monsters/{monster_id}', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;
            $campaignId = $args['id'];

            if (!self::isOwningDm($actor, $campaign)) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $encounterId = $args['enc_id'];
            $encounters = $campaign['encounters'] ?? [];
            if (!isset($encounters[$encounterId])) {
                return Json::response($response, ['error' => 'encounter not found'], 404);
            }

            $monsterId = $args['monster_id'];
            $encounter = $encounters[$encounterId];
            $monsters = $encounter['monsters'] ?? [];
            if (!isset($monsters[$monsterId])) {
                return Json::response($response, ['error' => 'monster not found'], 404);
            }

            unset($monsters[$monsterId]);
            $encounter['monsters'] = $monsters;
            $encounters[$encounterId] = $encounter;
            $campaign['encounters'] = $encounters;
            $campaigns->update($campaign);

            return Json::response($response, ['removed' => $monsterId], 200);
        });

        $app->post('/v1/play/campaigns/{id}/encounters/{enc_id}/combatants', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;
            $campaignId = $args['id'];

            if (!self::isOwningDm($actor, $campaign)) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $encounterId = $args['enc_id'];
            $encounters = $campaign['encounters'] ?? [];
            if (!isset($encounters[$encounterId])) {
                return Json::response($response, ['error' => 'encounter not found'], 404);
            }

            $body = Json::parseBody($request);
            $memberUsername = $body['member'] ?? null;
            $initiative = $body['initiative'] ?? null;

            if (!is_string($memberUsername) || $memberUsername === '') {
                return Json::response($response, ['error' => 'invalid member'], 400);
            }
            if (!is_int($initiative)) {
                return Json::response($response, ['error' => 'invalid initiative'], 400);
            }

            $member = $campaigns->memberByUsername($campaignId, $memberUsername);
            if ($member === null) {
                return Json::response($response, ['error' => 'member not found'], 400);
            }

            $encounter = $encounters[$encounterId];
            $combatants = $encounter['combatants'] ?? [];
            if (isset($combatants[$memberUsername])) {
                return Json::response($response, ['error' => 'combatant already exists'], 409);
            }

            $combatant = [
                'member' => $memberUsername,
                'character_id' => $member['character_id'],
                'name' => $member['name'],
                'initiative' => $initiative,
            ];
            $combatants[$memberUsername] = $combatant;
            $encounter['combatants'] = $combatants;
            $encounters[$encounterId] = $encounter;
            $campaign['encounters'] = $encounters;
            $campaigns->update($campaign);

            return Json::response($response, $combatant, 201);
        });

        $app->delete('/v1/play/campaigns/{id}/encounters/{enc_id}/combatants/{member}', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;
            $campaignId = $args['id'];

            if (!self::isOwningDm($actor, $campaign)) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $encounterId = $args['enc_id'];
            $encounters = $campaign['encounters'] ?? [];
            if (!isset($encounters[$encounterId])) {
                return Json::response($response, ['error' => 'encounter not found'], 404);
            }

            $memberUsername = $args['member'];
            $encounter = $encounters[$encounterId];
            $combatants = $encounter['combatants'] ?? [];
            if (!isset($combatants[$memberUsername])) {
                return Json::response($response, ['error' => 'combatant not found'], 404);
            }

            unset($combatants[$memberUsername]);
            $encounter['combatants'] = $combatants;
            $encounters[$encounterId] = $encounter;
            $campaign['encounters'] = $encounters;
            $campaigns->update($campaign);

            return Json::response($response, ['removed' => $memberUsername], 200);
        });

        $app->get('/v1/play/campaigns/{id}/encounters/{enc_id}/turn', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;
            $campaignId = $args['id'];

            $isOwner = $campaign['owner'] === $actor['username'];
            $isMember = $campaigns->memberByUsername($campaignId, $actor['username']) !== null;
            if (!$isOwner && !$isMember) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $encounter = self::requireEncounter($campaign, $response, $args['enc_id']);
            if ($encounter instanceof Response) {
                return $encounter;
            }

            $order = self::combatTurnOrder($encounter);
            if (empty($order)) {
                return Json::response($response, ['error' => 'no combatants'], 409);
            }

            $turnIndex = $encounter['turn_index'] ?? 0;
            if ($turnIndex >= count($order)) {
                $turnIndex = 0;
            }
            $active = $order[$turnIndex];

            return Json::response($response, [
                'round' => $encounter['turn_round'] ?? 1,
                'turn_index' => $turnIndex,
                'active' => [
                    'name' => $active['name'],
                    'kind' => $active['kind'],
                    'initiative' => $active['initiative'],
                ],
            ], 200);
        });

        $app->post('/v1/play/campaigns/{id}/encounters/{enc_id}/turn/advance', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;
            $campaignId = $args['id'];

            $isOwner = $campaign['owner'] === $actor['username'];
            $isMember = $campaigns->memberByUsername($campaignId, $actor['username']) !== null;
            if (!$isOwner && !$isMember) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $encounterId = $args['enc_id'];
            $encounter = self::requireEncounter($campaign, $response, $encounterId);
            if ($encounter instanceof Response) {
                return $encounter;
            }

            $order = self::combatTurnOrder($encounter);
            if (empty($order)) {
                return Json::response($response, ['error' => 'no combatants'], 409);
            }

            $round = $encounter['turn_round'] ?? 1;
            $turnIndex = $encounter['turn_index'] ?? 0;
            if ($turnIndex >= count($order)) {
                $turnIndex = 0;
            }
            $current = $order[$turnIndex];

            $isCurrentCombatant = $current['kind'] === 'player' && $current['key'] === $actor['username'];
            if (!$isOwner && !$isCurrentCombatant) {
                return Json::response($response, ['error' => 'not your turn'], 409);
            }

            $turnIndex++;
            if ($turnIndex >= count($order)) {
                $turnIndex = 0;
                $round++;
            }
            $active = $order[$turnIndex];

            $encounter['conditions'] = self::decrementConditions($encounter['conditions'] ?? [], $active['key']);
            $encounter['turn_round'] = $round;
            $encounter['turn_index'] = $turnIndex;
            $encounters = $campaign['encounters'];
            $encounters[$encounterId] = $encounter;
            $campaign['encounters'] = $encounters;
            $campaigns->update($campaign);

            return Json::response($response, [
                'round' => $round,
                'turn_index' => $turnIndex,
                'active' => [
                    'name' => $active['name'],
                    'kind' => $active['kind'],
                    'initiative' => $active['initiative'],
                ],
            ], 200);
        });

        $app->post('/v1/play/campaigns/{id}/encounters/{enc_id}/turn/delay', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;
            $campaignId = $args['id'];

            $isOwner = $campaign['owner'] === $actor['username'];
            $isMember = $campaigns->memberByUsername($campaignId, $actor['username']) !== null;
            if (!$isOwner && !$isMember) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $encounterId = $args['enc_id'];
            $encounter = self::requireEncounter($campaign, $response, $encounterId);
            if ($encounter instanceof Response) {
                return $encounter;
            }

            $order = self::combatTurnOrder($encounter);
            if (empty($order)) {
                return Json::response($response, ['error' => 'no combatants'], 409);
            }

            $turnIndex = $encounter['turn_index'] ?? 0;
            if ($turnIndex >= count($order)) {
                $turnIndex = 0;
            }
            $current = $order[$turnIndex];

            $isCurrentCombatant = $current['kind'] === 'player' && $current['key'] === $actor['username'];
            if (!$isOwner && !$isCurrentCombatant) {
                return Json::response($response, ['error' => 'not your turn'], 409);
            }

            $body = Json::parseBody($request);
            $newIndex = $body['new_index'] ?? $body['index'] ?? null;
            if (!is_int($newIndex) || $newIndex <= $turnIndex || $newIndex >= count($order)) {
                return Json::response($response, ['error' => 'invalid index'], 400);
            }

            $delayed = $order[$turnIndex];
            $newOrder = $order;
            array_splice($newOrder, $turnIndex, 1);
            array_splice($newOrder, $newIndex, 0, [$delayed]);

            $encounter['turn_order'] = array_map(fn ($entry) => $entry['key'], $newOrder);
            $encounter['turn_index'] = $newIndex;
            $encounters = $campaign['encounters'];
            $encounters[$encounterId] = $encounter;
            $campaign['encounters'] = $encounters;
            $campaigns->update($campaign);

            return Json::response($response, [
                'order' => $newOrder,
            ], 200);
        });

        $app->post('/v1/play/campaigns/{id}/encounters/{enc_id}/turn/ready', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;
            $campaignId = $args['id'];

            $isOwner = $campaign['owner'] === $actor['username'];
            $isMember = $campaigns->memberByUsername($campaignId, $actor['username']) !== null;
            if (!$isOwner && !$isMember) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $encounterId = $args['enc_id'];
            $encounter = self::requireEncounter($campaign, $response, $encounterId);
            if ($encounter instanceof Response) {
                return $encounter;
            }

            $order = self::combatTurnOrder($encounter);
            if (empty($order)) {
                return Json::response($response, ['error' => 'no combatants'], 409);
            }

            $turnIndex = $encounter['turn_index'] ?? 0;
            if ($turnIndex >= count($order)) {
                $turnIndex = 0;
            }
            $current = $order[$turnIndex];

            $isCurrentCombatant = $current['kind'] === 'player' && $current['key'] === $actor['username'];
            if (!$isCurrentCombatant) {
                return Json::response($response, ['error' => 'not your turn'], 409);
            }

            $body = Json::parseBody($request);
            $trigger = $body['trigger'] ?? null;
            if (!is_string($trigger) || $trigger === '') {
                return Json::response($response, ['error' => 'invalid trigger'], 400);
            }

            $readyRecord = [
                'actor' => $actor['username'],
                'trigger' => $trigger,
            ];

            $readyActions = $encounter['ready_actions'] ?? [];
            $readyActions[$actor['username']] = $readyRecord;
            $encounter['ready_actions'] = $readyActions;
            $encounters = $campaign['encounters'];
            $encounters[$encounterId] = $encounter;
            $campaign['encounters'] = $encounters;
            $campaigns->update($campaign);

            return Json::response($response, $readyRecord, 201);
        });

        $app->post('/v1/play/campaigns/{id}/encounters/{enc_id}/actions', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;
            $campaignId = $args['id'];

            $isOwner = $campaign['owner'] === $actor['username'];
            $isMember = $campaigns->memberByUsername($campaignId, $actor['username']) !== null;
            if (!$isOwner && !$isMember) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $encounterId = $args['enc_id'];
            $encounter = self::requireEncounter($campaign, $response, $encounterId);
            if ($encounter instanceof Response) {
                return $encounter;
            }

            $order = self::combatTurnOrder($encounter);
            if (empty($order)) {
                return Json::response($response, ['error' => 'no combatants'], 409);
            }

            $turnIndex = $encounter['turn_index'] ?? 0;
            if ($turnIndex >= count($order)) {
                $turnIndex = 0;
            }
            $current = $order[$turnIndex];

            $isCurrentCombatant = $current['kind'] === 'player' && $current['key'] === $actor['username'];
            if (!$isCurrentCombatant) {
                return Json::response($response, ['error' => 'not your turn'], 409);
            }

            $body = Json::parseBody($request);
            $type = $body['type'] ?? null;
            $target = $body['target'] ?? null;
            $text = $body['text'] ?? null;

            $validTypes = ['attack', 'help', 'dodge', 'ready'];
            if (!is_string($type) || !in_array($type, $validTypes, true)) {
                return Json::response($response, ['error' => 'invalid type'], 400);
            }
            if (!is_string($text) || $text === '') {
                return Json::response($response, ['error' => 'invalid text'], 400);
            }
            if ($target !== null && !is_string($target)) {
                return Json::response($response, ['error' => 'invalid target'], 400);
            }

            $sequence = $campaigns->nextEventSequence($campaignId);
            $event = [
                'sequence' => $sequence,
                'kind' => 'combat_action',
                'actor' => $actor['username'],
                'type' => $type,
                'target' => $target,
                'text' => $text,
            ];
            $campaigns->insertEvent($campaignId, $sequence, $event);

            return Json::response($response, $event, 201);
        });

        $app->post('/v1/play/campaigns/{id}/encounters/{enc_id}/conditions', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;
            $campaignId = $args['id'];

            if (!self::isOwningDm($actor, $campaign)) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $encounterId = $args['enc_id'];
            $encounter = self::requireEncounter($campaign, $response, $encounterId);
            if ($encounter instanceof Response) {
                return $encounter;
            }

            $body = Json::parseBody($request);
            $target = $body['target'] ?? null;
            $condition = $body['condition'] ?? null;
            $durationRounds = $body['duration_rounds'] ?? null;

            if (!is_string($target) || $target === '') {
                return Json::response($response, ['error' => 'invalid target'], 400);
            }
            if (!is_string($condition) || $condition === '') {
                return Json::response($response, ['error' => 'invalid condition'], 400);
            }
            if (!is_int($durationRounds) || $durationRounds <= 0) {
                return Json::response($response, ['error' => 'invalid duration_rounds'], 400);
            }

            $monsters = $encounter['monsters'] ?? [];
            $combatants = $encounter['combatants'] ?? [];
            if (!isset($monsters[$target]) && !isset($combatants[$target])) {
                return Json::response($response, ['error' => 'target not found'], 404);
            }

            $conditions = $encounter['conditions'] ?? [];
            $targetConditions = $conditions[$target] ?? [];

            $found = false;
            foreach ($targetConditions as &$existing) {
                if ($existing['condition'] === $condition) {
                    $existing['remaining_rounds'] = $durationRounds;
                    $found = true;
                    break;
                }
            }
            unset($existing);
            if (!$found) {
                $targetConditions[] = ['condition' => $condition, 'remaining_rounds' => $durationRounds];
            }

            $conditions[$target] = $targetConditions;
            $encounter['conditions'] = $conditions;
            $encounters = $campaign['encounters'];
            $encounters[$encounterId] = $encounter;
            $campaign['encounters'] = $encounters;
            $campaigns->update($campaign);

            return Json::response($response, [
                'target' => $target,
                'conditions' => $targetConditions,
            ], 201);
        });

        $app->get('/v1/play/campaigns/{id}/encounters/{enc_id}/status', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;
            $campaignId = $args['id'];

            $isOwner = $campaign['owner'] === $actor['username'];
            $isMember = $campaigns->memberByUsername($campaignId, $actor['username']) !== null;
            if (!$isOwner && !$isMember) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $encounter = self::requireEncounter($campaign, $response, $args['enc_id']);
            if ($encounter instanceof Response) {
                return $encounter;
            }

            $order = self::combatTurnOrder($encounter);
            $turnIndex = $encounter['turn_index'] ?? 0;
            if (!empty($order) && $turnIndex >= count($order)) {
                $turnIndex = 0;
            }
            $active = empty($order) ? null : [
                'name' => $order[$turnIndex]['name'],
                'kind' => $order[$turnIndex]['kind'],
                'initiative' => $order[$turnIndex]['initiative'],
            ];

            return Json::response($response, [
                'round' => $encounter['turn_round'] ?? 1,
                'turn_index' => $turnIndex,
                'active' => $active,
                'order' => $order,
                'conditions' => $encounter['conditions'] ?? [],
            ], 200);
        });

        $app->post('/v1/play/campaigns/{id}/encounters/{enc_id}/rewards', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;
            $campaignId = $args['id'];

            if (!self::isOwningDm($actor, $campaign)) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $encounterId = $args['enc_id'];
            $encounter = self::requireEncounter($campaign, $response, $encounterId);
            if ($encounter instanceof Response) {
                return $encounter;
            }

            if (isset($encounter['rewards'])) {
                return Json::response($response, ['error' => 'rewards already awarded'], 409);
            }

            $body = Json::parseBody($request);
            $xp = $body['xp'] ?? null;
            $loot = $body['loot'] ?? [];

            if (!is_int($xp) || $xp < 0) {
                return Json::response($response, ['error' => 'invalid xp'], 400);
            }
            if (!is_array($loot)) {
                return Json::response($response, ['error' => 'invalid loot'], 400);
            }

            $normalizedLoot = [];
            foreach ($loot as $item) {
                $slug = $item['slug'] ?? null;
                $quantity = $item['quantity'] ?? null;
                if (!is_string($slug) || $slug === '') {
                    return Json::response($response, ['error' => 'invalid loot slug'], 400);
                }
                if (!is_int($quantity) || $quantity <= 0) {
                    return Json::response($response, ['error' => 'invalid loot quantity'], 400);
                }
                $normalizedLoot[] = ['slug' => $slug, 'quantity' => $quantity];
            }

            $rewards = [
                'id' => $encounterId,
                'xp' => $xp,
                'loot' => $normalizedLoot,
            ];

            $encounter['rewards'] = $rewards;
            $encounters = $campaign['encounters'];
            $encounters[$encounterId] = $encounter;
            $campaign['encounters'] = $encounters;
            $campaigns->update($campaign);

            return Json::response($response, $rewards, 200);
        });

        $app->post('/v1/play/campaigns/{id}/encounters/{enc_id}/close', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;
            $campaignId = $args['id'];

            if (!self::isOwningDm($actor, $campaign)) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $encounterId = $args['enc_id'];
            $encounter = self::requireEncounter($campaign, $response, $encounterId);
            if ($encounter instanceof Response) {
                return $encounter;
            }

            $encounter['status'] = 'closed';
            $xpAwarded = $encounter['rewards']['xp'] ?? 0;

            $encounters = $campaign['encounters'];
            $encounters[$encounterId] = $encounter;
            $campaign['encounters'] = $encounters;
            $campaigns->update($campaign);

            return Json::response($response, [
                'id' => $encounterId,
                'status' => 'closed',
                'xp_awarded' => $xpAwarded,
            ], 200);
        });

        $app->post('/v1/play/campaigns/{id}/encounters/{enc_id}/end', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;
            $campaignId = $args['id'];

            if (!self::isOwningDm($actor, $campaign)) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $encounterId = $args['enc_id'];
            $encounter = self::requireEncounter($campaign, $response, $encounterId);
            if ($encounter instanceof Response) {
                return $encounter;
            }

            if (!($campaign['in_combat'] ?? false)) {
                return Json::response($response, ['error' => 'campaign not in combat'], 409);
            }

            if ($encounter['status'] === 'active') {
                $encounter['status'] = 'closed';
                $encounters = $campaign['encounters'];
                $encounters[$encounterId] = $encounter;
                $campaign['encounters'] = $encounters;
            }

            $campaign['current_actor'] = $campaign['pre_combat_actor'] ?? $campaign['owner'];
            unset($campaign['pre_combat_actor']);
            $campaign['in_combat'] = false;
            $campaigns->update($campaign);

            return Json::response($response, [
                'campaign_id' => $campaign['id'],
                'status' => $campaign['status'],
                'phase' => 'exploration',
                'current_actor' => $campaign['current_actor'],
            ], 200);
        });

        $app->post('/v1/play/campaigns/{id}/encounters/{enc_id}/damage', function (Request $request, Response $response, array $args) use ($dbFile) {
            return self::applyHpChange($request, $response, $args, $dbFile, 'damage');
        });

        $app->post('/v1/play/campaigns/{id}/encounters/{enc_id}/heal', function (Request $request, Response $response, array $args) use ($dbFile) {
            return self::applyHpChange($request, $response, $args, $dbFile, 'heal');
        });

        $app->post('/v1/play/campaigns/{id}/characters/{char_id}/damage', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;
            $campaignId = $args['id'];

            if (!self::isOwningDm($actor, $campaign)) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $characterId = $args['char_id'];
            $member = $campaigns->memberByCharacterId($campaignId, $characterId);
            if ($member === null) {
                return Json::response($response, ['error' => 'character not found'], 404);
            }
            $member = self::withDeathSaveDefaults($member);

            $body = Json::parseBody($request);
            $amount = $body['amount'] ?? null;
            if (!is_int($amount) || $amount < 0) {
                return Json::response($response, ['error' => 'invalid amount'], 400);
            }

            $hpBefore = $member['hp_current'];
            $hpAfter = max(0, $hpBefore - $amount);
            $member['hp_current'] = $hpAfter;

            if ($hpAfter === 0 && $member['status'] === 'alive') {
                $member['status'] = 'unconscious';
                $member['death_save_successes'] = 0;
                $member['death_save_failures'] = 0;
            }

            $campaigns->updateMember($campaignId, $member['username'], $member);

            return Json::response($response, [
                'character_id' => $characterId,
                'target' => $characterId,
                'hp_before' => $hpBefore,
                'hp_after' => $hpAfter,
                'damage' => $amount,
                'status' => $member['status'],
            ], 200);
        });

        $app->post('/v1/play/campaigns/{id}/characters/{char_id}/death-saves', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;
            $campaignId = $args['id'];

            $characterId = $args['char_id'];
            $member = $campaigns->memberByCharacterId($campaignId, $characterId);
            if ($member === null) {
                return Json::response($response, ['error' => 'character not found'], 404);
            }
            $member = self::withDeathSaveDefaults($member);

            if ($member['username'] !== $actor['username']) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            if ($member['status'] !== 'unconscious') {
                return Json::response($response, ['error' => 'character is not unconscious'], 409);
            }

            $body = Json::parseBody($request);
            $outcome = $body['outcome'] ?? null;
            if ($outcome !== 'success' && $outcome !== 'failure') {
                return Json::response($response, ['error' => 'invalid outcome'], 400);
            }

            if ($outcome === 'success') {
                $member['death_save_successes']++;
                if ($member['death_save_successes'] >= 3) {
                    $member['status'] = 'stable';
                }
            } else {
                $member['death_save_failures']++;
                if ($member['death_save_failures'] >= 3) {
                    $member['status'] = 'dead';
                }
            }

            $campaigns->updateMember($campaignId, $member['username'], $member);

            return Json::response($response, [
                'character_id' => $characterId,
                'successes' => $member['death_save_successes'],
                'failures' => $member['death_save_failures'],
                'status' => $member['status'],
            ], 201);
        });

        $app->get('/v1/play/campaigns/{id}/characters/{char_id}/status', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;
            $campaignId = $args['id'];

            $isMember = self::isOwningDm($actor, $campaign)
                || $campaigns->memberByUsername($campaignId, $actor['username']) !== null;
            if (!$isMember) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $characterId = $args['char_id'];
            $member = $campaigns->memberByCharacterId($campaignId, $characterId);
            if ($member === null) {
                return Json::response($response, ['error' => 'character not found'], 404);
            }
            $member = self::withDeathSaveDefaults($member);

            return Json::response($response, [
                'character_id' => $characterId,
                'hp_current' => $member['hp_current'],
                'hp_max' => $member['hp_max'],
                'status' => $member['status'],
            ], 200);
        });

        $app->get('/v1/play/campaigns/{id}/characters/{char_id}/owner', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;
            $campaignId = $args['id'];

            $isMember = self::isOwningDm($actor, $campaign)
                || $campaigns->memberByUsername($campaignId, $actor['username']) !== null;
            if (!$isMember) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $characterId = $args['char_id'];
            $member = $campaigns->memberByCharacterId($campaignId, $characterId);
            if ($member === null) {
                return Json::response($response, ['error' => 'character not found'], 404);
            }
            $member = self::withOwnerDefaults($member);

            return Json::response($response, [
                'character_id' => $characterId,
                'owner' => $member['owner'],
            ], 200);
        });

        $app->post('/v1/play/campaigns/{id}/characters/{char_id}/claim', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;
            $campaignId = $args['id'];

            if ($campaigns->memberByUsername($campaignId, $actor['username']) === null) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $characterId = $args['char_id'];
            $member = $campaigns->memberByCharacterId($campaignId, $characterId);
            if ($member === null) {
                return Json::response($response, ['error' => 'character not found'], 404);
            }
            $member = self::withOwnerDefaults($member);

            if ($member['owner'] !== null) {
                return Json::response($response, ['error' => 'character already owned'], 409);
            }

            $member['owner'] = $actor['username'];
            $campaigns->updateMember($campaignId, $member['username'], $member);

            return Json::response($response, [
                'character_id' => $characterId,
                'owner' => $member['owner'],
            ], 201);
        });

        $app->post('/v1/play/campaigns/{id}/characters/{char_id}/transfer', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;
            $campaignId = $args['id'];

            $characterId = $args['char_id'];
            $member = $campaigns->memberByCharacterId($campaignId, $characterId);
            if ($member === null) {
                return Json::response($response, ['error' => 'character not found'], 404);
            }
            $member = self::withOwnerDefaults($member);

            if ($member['owner'] !== $actor['username']) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $body = Json::parseBody($request);
            $newOwner = $body['new_owner'] ?? null;
            if (!is_string($newOwner) || $newOwner === '') {
                return Json::response($response, ['error' => 'invalid new_owner'], 400);
            }
            if ($campaigns->memberByUsername($campaignId, $newOwner) === null) {
                return Json::response($response, ['error' => 'member not found'], 400);
            }

            $member['owner'] = $newOwner;
            $campaigns->updateMember($campaignId, $member['username'], $member);

            return Json::response($response, [
                'character_id' => $characterId,
                'owner' => $member['owner'],
            ], 200);
        });

        $app->post('/v1/play/campaigns/{id}/characters/{char_id}/build', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;
            $campaignId = $args['id'];

            $characterId = $args['char_id'];
            $member = $campaigns->memberByCharacterId($campaignId, $characterId);
            if ($member === null) {
                return Json::response($response, ['error' => 'character not found'], 404);
            }
            $member = self::withOwnerDefaults($member);

            if ($member['owner'] !== $actor['username']) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $body = Json::parseBody($request);
            $race = $body['race'] ?? null;
            $class = $body['class'] ?? null;
            $background = $body['background'] ?? null;
            $abilities = $body['abilities'] ?? null;

            if (!is_string($race) || !in_array($race, Characters::RACES, true)) {
                return Json::response($response, ['error' => 'invalid race'], 400);
            }
            if (!is_string($class) || !in_array($class, Characters::CLASSES, true)) {
                return Json::response($response, ['error' => 'invalid class'], 400);
            }
            if (!is_string($background) || !in_array($background, Characters::BACKGROUNDS, true)) {
                return Json::response($response, ['error' => 'invalid background'], 400);
            }
            if (!is_array($abilities)) {
                return Json::response($response, ['error' => 'invalid abilities'], 400);
            }

            $abilityKeys = ['str', 'dex', 'con', 'int', 'wis', 'cha'];
            foreach ($abilityKeys as $key) {
                $score = $abilities[$key] ?? null;
                if (!Validation::isIntInRange($score, 1, 30)) {
                    return Json::response($response, ['error' => 'invalid ability score'], 400);
                }
            }

            $conModifier = Characters::abilityModifier($abilities['con']);
            $level = 1;

            $member['race'] = $race;
            $member['class'] = $class;
            $member['background'] = $background;
            $member['abilities'] = $abilities;
            $member['level'] = $level;
            $member['hp_max'] = Characters::level1HpMax($class, $conModifier);
            $member['hp_current'] = $member['hp_max'];
            $campaigns->updateMember($campaignId, $member['username'], $member);

            return Json::response($response, [
                'character_id' => $characterId,
                'race' => $race,
                'class' => $class,
                'background' => $background,
                'level' => $level,
                'hp_max' => $member['hp_max'],
                'proficiency_bonus' => Characters::proficiencyBonus($level),
            ], 200);
        });

        $app->post('/v1/play/campaigns/{id}/characters/{char_id}/level-up', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;
            $campaignId = $args['id'];

            $characterId = $args['char_id'];
            $member = $campaigns->memberByCharacterId($campaignId, $characterId);
            if ($member === null) {
                return Json::response($response, ['error' => 'character not found'], 404);
            }
            $member = self::withOwnerDefaults($member);

            if ($member['owner'] !== $actor['username']) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $body = Json::parseBody($request);
            $newLevel = $body['level'] ?? null;
            $currentLevel = $member['level'] ?? 1;

            if (!is_int($newLevel) || $newLevel !== $currentLevel + 1) {
                return Json::response($response, ['error' => 'invalid level'], 400);
            }

            $class = $member['class'] ?? null;
            if (!is_string($class) || !in_array($class, Characters::CLASSES, true)) {
                return Json::response($response, ['error' => 'character has no class'], 400);
            }

            $conScore = $member['abilities']['con'] ?? 10;
            $conModifier = Characters::abilityModifier($conScore);
            $hpGain = Characters::levelUpHpGain($class, $conModifier);

            $member['level'] = $newLevel;
            $member['hp_max'] = ($member['hp_max'] ?? 0) + $hpGain;
            $member['hp_current'] = ($member['hp_current'] ?? $member['hp_max']) + $hpGain;
            $campaigns->updateMember($campaignId, $member['username'], $member);

            return Json::response($response, [
                'character_id' => $characterId,
                'level' => $newLevel,
                'hp_max' => $member['hp_max'],
                'hit_dice' => '1d' . Characters::hitDieSize($class),
                'proficiency_bonus' => Characters::proficiencyBonus($newLevel),
            ], 200);
        });

        $app->post('/v1/play/campaigns/{id}/characters/{char_id}/skill-check', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;
            $campaignId = $args['id'];

            $characterId = $args['char_id'];
            $member = $campaigns->memberByCharacterId($campaignId, $characterId);
            if ($member === null) {
                return Json::response($response, ['error' => 'character not found'], 404);
            }
            $member = self::withOwnerDefaults($member);

            if ($member['owner'] !== $actor['username']) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $body = Json::parseBody($request);
            $skill = $body['skill'] ?? null;
            $ability = $body['ability'] ?? null;
            $proficient = $body['proficient'] ?? null;
            $roll = $body['roll'] ?? null;

            if (!is_string($skill) || !isset(Characters::SKILL_ABILITIES[$skill])) {
                return Json::response($response, ['error' => 'invalid skill'], 400);
            }
            if (!is_string($ability) || $ability !== Characters::SKILL_ABILITIES[$skill]) {
                return Json::response($response, ['error' => 'invalid ability'], 400);
            }
            if (!is_bool($proficient)) {
                return Json::response($response, ['error' => 'invalid proficient'], 400);
            }
            if (!is_int($roll)) {
                return Json::response($response, ['error' => 'invalid roll'], 400);
            }

            $abilityScore = $member['abilities'][$ability] ?? 10;
            $level = $member['level'] ?? 1;

            $abilityModifier = Characters::abilityModifier($abilityScore);
            $modifier = $abilityModifier + ($proficient ? Characters::proficiencyBonus($level) : 0);
            $total = $roll + $modifier;

            return Json::response($response, [
                'character_id' => $characterId,
                'skill' => $skill,
                'ability' => $ability,
                'modifier' => $modifier,
                'total' => $total,
            ], 200);
        });

        $app->post('/v1/play/campaigns/{id}/characters/{char_id}/spells', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;
            $campaignId = $args['id'];

            $characterId = $args['char_id'];
            $member = $campaigns->memberByCharacterId($campaignId, $characterId);
            if ($member === null) {
                return Json::response($response, ['error' => 'character not found'], 404);
            }
            $member = self::withOwnerDefaults($member);

            if ($member['owner'] !== $actor['username']) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $body = Json::parseBody($request);
            $spellId = $body['spell_id'] ?? null;
            $name = $body['name'] ?? null;
            $level = $body['level'] ?? null;

            if (!is_string($spellId) || $spellId === '') {
                return Json::response($response, ['error' => 'invalid spell_id'], 400);
            }
            if (!is_string($name) || $name === '') {
                return Json::response($response, ['error' => 'invalid name'], 400);
            }
            if (!is_int($level) || $level < 0 || $level > 9) {
                return Json::response($response, ['error' => 'invalid level'], 400);
            }

            $class = $member['class'] ?? null;
            if (!is_string($class) || !Spells::isValidForClass($spellId, $class)) {
                return Json::response($response, ['error' => 'invalid class/spell combination'], 400);
            }

            $spells = $member['spells'] ?? [];
            if (isset($spells[$spellId])) {
                return Json::response($response, ['error' => 'spell already known'], 409);
            }

            $spell = [
                'spell_id' => $spellId,
                'name' => $name,
                'level' => $level,
            ];
            $spells[$spellId] = $spell;
            $member['spells'] = $spells;
            $campaigns->updateMember($campaignId, $member['username'], $member);

            return Json::response($response, $spell, 201);
        });

        $app->get('/v1/play/campaigns/{id}/characters/{char_id}/spells', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;
            $campaignId = $args['id'];

            $isMember = self::isOwningDm($actor, $campaign)
                || $campaigns->memberByUsername($campaignId, $actor['username']) !== null;
            if (!$isMember) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $characterId = $args['char_id'];
            $member = $campaigns->memberByCharacterId($campaignId, $characterId);
            if ($member === null) {
                return Json::response($response, ['error' => 'character not found'], 404);
            }

            $spells = array_values($member['spells'] ?? []);

            return Json::response($response, ['spells' => $spells], 200);
        });

        $app->put('/v1/play/campaigns/{id}/characters/{char_id}/prepared-spells', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;
            $campaignId = $args['id'];

            $characterId = $args['char_id'];
            $member = $campaigns->memberByCharacterId($campaignId, $characterId);
            if ($member === null) {
                return Json::response($response, ['error' => 'character not found'], 404);
            }
            $member = self::withOwnerDefaults($member);

            if ($member['owner'] !== $actor['username']) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $class = $member['class'] ?? null;
            if ($class !== 'wizard') {
                return Json::response($response, ['error' => 'not a spellcaster'], 400);
            }

            $body = Json::parseBody($request);
            $spellIds = $body['spell_ids'] ?? null;
            if (!is_array($spellIds)) {
                return Json::response($response, ['error' => 'invalid spell_ids'], 400);
            }

            $maxPrepared = 1;
            if (count($spellIds) > $maxPrepared) {
                return Json::response($response, ['error' => 'too many spells'], 400);
            }

            $known = $member['spells'] ?? [];
            foreach ($spellIds as $spellId) {
                if (!is_string($spellId) || !isset($known[$spellId])) {
                    return Json::response($response, ['error' => 'unknown spell'], 400);
                }
            }

            $member['prepared_spells'] = array_values($spellIds);
            $campaigns->updateMember($campaignId, $member['username'], $member);

            return Json::response($response, [
                'character_id' => $characterId,
                'prepared_spells' => array_values($spellIds),
                'max_prepared' => $maxPrepared,
            ], 200);
        });

        $app->get('/v1/play/campaigns/{id}/characters/{char_id}/prepared-spells', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;
            $campaignId = $args['id'];

            $isMember = self::isOwningDm($actor, $campaign)
                || $campaigns->memberByUsername($campaignId, $actor['username']) !== null;
            if (!$isMember) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $characterId = $args['char_id'];
            $member = $campaigns->memberByCharacterId($campaignId, $characterId);
            if ($member === null) {
                return Json::response($response, ['error' => 'character not found'], 404);
            }

            $prepared = array_values($member['prepared_spells'] ?? []);

            return Json::response($response, [
                'character_id' => $characterId,
                'prepared_spells' => $prepared,
                'max_prepared' => 1,
            ], 200);
        });

        $app->post('/v1/play/campaigns/{id}/characters/{char_id}/casts', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;
            $campaignId = $args['id'];

            $characterId = $args['char_id'];
            $member = $campaigns->memberByCharacterId($campaignId, $characterId);
            if ($member === null) {
                return Json::response($response, ['error' => 'character not found'], 404);
            }
            $member = self::withOwnerDefaults($member);
            $member = self::withCastDefaults($member);

            if ($member['owner'] !== $actor['username']) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $body = Json::parseBody($request);
            $spellId = $body['spell_id'] ?? null;
            $target = $body['target'] ?? null;

            if (!is_string($spellId) || $spellId === '') {
                return Json::response($response, ['error' => 'invalid spell_id'], 400);
            }
            if (!is_string($target) || $target === '') {
                return Json::response($response, ['error' => 'invalid target'], 400);
            }

            $class = $member['class'] ?? null;
            if ($class !== 'wizard') {
                return Json::response($response, ['error' => 'not a spellcaster'], 400);
            }

            $prepared = $member['prepared_spells'] ?? [];
            if (!in_array($spellId, $prepared, true)) {
                return Json::response($response, ['error' => 'spell not prepared'], 400);
            }

            $spell = Spells::SPELLS[$spellId] ?? null;
            if ($spell === null) {
                return Json::response($response, ['error' => 'invalid spell_id'], 400);
            }

            $slotLevel = $spell['level'];
            $characterLevel = $member['level'] ?? 1;
            $totalSlots = Spells::slotsForCharacterLevel($characterLevel, $slotLevel);

            $casts = $member['casts'];
            $castsOfLevel = 0;
            foreach ($casts as $cast) {
                if ($cast['slot_level'] === $slotLevel) {
                    $castsOfLevel++;
                }
            }

            $slotsRemaining = $totalSlots - $castsOfLevel;
            if ($slotsRemaining <= 0) {
                return Json::response($response, ['error' => 'no remaining spell slots'], 409);
            }

            $cast = [
                'character_id' => $characterId,
                'spell_id' => $spellId,
                'target' => $target,
                'slot_level' => $slotLevel,
                'slots_remaining' => $slotsRemaining - 1,
                'sequence' => count($casts) + 1,
            ];
            $casts[] = $cast;
            $member['casts'] = $casts;
            $campaigns->updateMember($campaignId, $member['username'], $member);

            return Json::response($response, $cast, 201);
        });

        $app->get('/v1/play/campaigns/{id}/characters/{char_id}/casts', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;
            $campaignId = $args['id'];

            $isMember = self::isOwningDm($actor, $campaign)
                || $campaigns->memberByUsername($campaignId, $actor['username']) !== null;
            if (!$isMember) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $characterId = $args['char_id'];
            $member = $campaigns->memberByCharacterId($campaignId, $characterId);
            if ($member === null) {
                return Json::response($response, ['error' => 'character not found'], 404);
            }
            $member = self::withCastDefaults($member);

            return Json::response($response, ['casts' => array_values($member['casts'])], 200);
        });

        $app->put('/v1/play/campaigns/{id}/characters/{character_id}/concentration', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;
            $campaignId = $args['id'];

            $characterId = $args['character_id'];
            $member = $campaigns->memberByCharacterId($campaignId, $characterId);
            if ($member === null) {
                return Json::response($response, ['error' => 'character not found'], 404);
            }
            $member = self::withOwnerDefaults($member);
            $member = self::withConcentrationDefaults($member);

            if ($member['owner'] !== $actor['username']) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $body = Json::parseBody($request);
            $spellId = $body['spell_id'] ?? null;
            $target = $body['target'] ?? null;
            $durationTurns = $body['duration_turns'] ?? null;

            if (!is_string($spellId) || $spellId === '') {
                return Json::response($response, ['error' => 'invalid spell_id'], 400);
            }
            if (!is_string($target) || $target === '') {
                return Json::response($response, ['error' => 'invalid target'], 400);
            }
            if (!is_int($durationTurns) || $durationTurns < 1) {
                return Json::response($response, ['error' => 'invalid duration_turns'], 400);
            }

            $class = $member['class'] ?? null;
            if ($class !== 'wizard') {
                return Json::response($response, ['error' => 'not a spellcaster'], 400);
            }

            $known = $member['spells'] ?? [];
            if (!isset($known[$spellId])) {
                return Json::response($response, ['error' => 'unknown spell'], 400);
            }

            $prepared = $member['prepared_spells'] ?? [];
            if (!in_array($spellId, $prepared, true)) {
                return Json::response($response, ['error' => 'spell not prepared'], 400);
            }

            $concentration = [
                'spell_id' => $spellId,
                'target' => $target,
                'remaining_turns' => $durationTurns,
            ];
            $member['concentration'] = $concentration;
            $campaigns->updateMember($campaignId, $member['username'], $member);

            return Json::response($response, [
                'character_id' => $characterId,
                'concentration' => $concentration,
            ], 200);
        });

        $app->get('/v1/play/campaigns/{id}/characters/{character_id}/concentration', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;
            $campaignId = $args['id'];

            $isMember = self::isOwningDm($actor, $campaign)
                || $campaigns->memberByUsername($campaignId, $actor['username']) !== null;
            if (!$isMember) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $characterId = $args['character_id'];
            $member = $campaigns->memberByCharacterId($campaignId, $characterId);
            if ($member === null) {
                return Json::response($response, ['error' => 'character not found'], 404);
            }
            $member = self::withConcentrationDefaults($member);

            return Json::response($response, [
                'character_id' => $characterId,
                'concentration' => $member['concentration'],
            ], 200);
        });

        $app->post('/v1/play/campaigns/{id}/characters/{character_id}/concentration/advance-turn', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;
            $campaignId = $args['id'];

            $isMember = self::isOwningDm($actor, $campaign)
                || $campaigns->memberByUsername($campaignId, $actor['username']) !== null;
            if (!$isMember) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $characterId = $args['character_id'];
            $member = $campaigns->memberByCharacterId($campaignId, $characterId);
            if ($member === null) {
                return Json::response($response, ['error' => 'character not found'], 404);
            }
            $member = self::withConcentrationDefaults($member);

            $concentration = $member['concentration'];
            if ($concentration !== null) {
                $remaining = $concentration['remaining_turns'] - 1;
                if ($remaining <= 0) {
                    $concentration = null;
                } else {
                    $concentration['remaining_turns'] = $remaining;
                }
                $member['concentration'] = $concentration;
                $campaigns->updateMember($campaignId, $member['username'], $member);
            }

            return Json::response($response, [
                'character_id' => $characterId,
                'concentration' => $concentration,
            ], 200);
        });

        $app->delete('/v1/play/campaigns/{id}/characters/{character_id}/concentration', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;
            $campaignId = $args['id'];

            $characterId = $args['character_id'];
            $member = $campaigns->memberByCharacterId($campaignId, $characterId);
            if ($member === null) {
                return Json::response($response, ['error' => 'character not found'], 404);
            }
            $member = self::withOwnerDefaults($member);
            $member = self::withConcentrationDefaults($member);

            if ($member['owner'] !== $actor['username']) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $member['concentration'] = null;
            $campaigns->updateMember($campaignId, $member['username'], $member);

            return Json::response($response, [
                'character_id' => $characterId,
                'concentration' => null,
            ], 200);
        });

        $app->post('/v1/play/campaigns/{id}/characters/{character_id}/inventory/items', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;
            $campaignId = $args['id'];

            $characterId = $args['character_id'];
            $member = $campaigns->memberByCharacterId($campaignId, $characterId);
            if ($member === null) {
                return Json::response($response, ['error' => 'character not found'], 404);
            }
            $member = self::withOwnerDefaults($member);
            $member = self::withInventoryDefaults($member);

            if ($member['owner'] !== $actor['username']) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $body = Json::parseBody($request);
            $itemId = $body['item_id'] ?? null;
            $quantity = $body['quantity'] ?? null;

            if (!in_array($itemId, self::INVENTORY_ITEM_IDS, true)) {
                return Json::response($response, ['error' => 'invalid item_id'], 400);
            }
            if (!is_int($quantity) || $quantity < 1) {
                return Json::response($response, ['error' => 'invalid quantity'], 400);
            }

            $items = $member['inventory'];
            $items[$itemId] = ($items[$itemId] ?? 0) + $quantity;
            $member['inventory'] = $items;
            $campaigns->updateMember($campaignId, $member['username'], $member);

            return Json::response($response, [
                'character_id' => $characterId,
                'item_id' => $itemId,
                'quantity' => $quantity,
                'total_quantity' => $items[$itemId],
            ], 201);
        });

        $app->get('/v1/play/campaigns/{id}/characters/{character_id}/inventory/items', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;
            $campaignId = $args['id'];

            $isMember = self::isOwningDm($actor, $campaign)
                || $campaigns->memberByUsername($campaignId, $actor['username']) !== null;
            if (!$isMember) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $characterId = $args['character_id'];
            $member = $campaigns->memberByCharacterId($campaignId, $characterId);
            if ($member === null) {
                return Json::response($response, ['error' => 'character not found'], 404);
            }
            $member = self::withInventoryDefaults($member);

            $items = $member['inventory'];
            ksort($items);
            $itemList = [];
            foreach ($items as $itemId => $quantity) {
                $itemList[] = ['item_id' => $itemId, 'quantity' => $quantity];
            }

            return Json::response($response, [
                'character_id' => $characterId,
                'items' => $itemList,
            ], 200);
        });

        $app->delete('/v1/play/campaigns/{id}/characters/{character_id}/inventory/items/{item_id}', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;
            $campaignId = $args['id'];

            $characterId = $args['character_id'];
            $member = $campaigns->memberByCharacterId($campaignId, $characterId);
            if ($member === null) {
                return Json::response($response, ['error' => 'character not found'], 404);
            }
            $member = self::withOwnerDefaults($member);
            $member = self::withInventoryDefaults($member);

            if ($member['owner'] !== $actor['username']) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $itemId = $args['item_id'];
            if (!in_array($itemId, self::INVENTORY_ITEM_IDS, true)) {
                return Json::response($response, ['error' => 'invalid item_id'], 400);
            }

            $body = Json::parseBody($request);
            $quantity = $body['quantity'] ?? null;
            if (!is_int($quantity) || $quantity < 1) {
                return Json::response($response, ['error' => 'invalid quantity'], 400);
            }

            $items = $member['inventory'];
            $held = $items[$itemId] ?? 0;
            if ($quantity > $held) {
                return Json::response($response, ['error' => 'insufficient quantity'], 409);
            }

            $remaining = $held - $quantity;
            if ($remaining > 0) {
                $items[$itemId] = $remaining;
            } else {
                unset($items[$itemId]);
            }
            $member['inventory'] = $items;
            $campaigns->updateMember($campaignId, $member['username'], $member);

            return Json::response($response, [
                'character_id' => $characterId,
                'item_id' => $itemId,
                'quantity' => $quantity,
                'total_quantity' => $remaining,
            ], 200);
        });
        $app->post('/v1/play/campaigns/{id}/characters/{character_id}/inventory/items/{item_id}/consume', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;
            $campaignId = $args['id'];

            $characterId = $args['character_id'];
            $member = $campaigns->memberByCharacterId($campaignId, $characterId);
            if ($member === null) {
                return Json::response($response, ['error' => 'character not found'], 404);
            }
            $member = self::withOwnerDefaults($member);
            $member = self::withInventoryDefaults($member);

            if ($member['owner'] !== $actor['username']) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $itemId = $args['item_id'];
            if (!in_array($itemId, self::INVENTORY_ITEM_IDS, true) || !in_array($itemId, self::CONSUMABLE_ITEM_IDS, true)) {
                return Json::response($response, ['error' => 'invalid item_id'], 400);
            }

            $items = $member['inventory'];
            $held = $items[$itemId] ?? 0;
            if ($held < 1) {
                return Json::response($response, ['error' => 'no held quantity'], 409);
            }

            $remaining = $held - 1;
            if ($remaining > 0) {
                $items[$itemId] = $remaining;
            } else {
                unset($items[$itemId]);
            }
            $member['inventory'] = $items;
            $campaigns->updateMember($campaignId, $member['username'], $member);

            return Json::response($response, [
                'character_id' => $characterId,
                'item_id' => $itemId,
                'quantity_consumed' => 1,
                'total_quantity' => $remaining,
                'effect' => self::CONSUMABLE_EFFECTS[$itemId],
            ], 200);
        });

        $app->get('/v1/play/campaigns/{id}/characters/{character_id}/currency', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;
            $campaignId = $args['id'];

            $isMember = self::isOwningDm($actor, $campaign)
                || $campaigns->memberByUsername($campaignId, $actor['username']) !== null;
            if (!$isMember) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $characterId = $args['character_id'];
            $member = $campaigns->memberByCharacterId($campaignId, $characterId);
            if ($member === null) {
                return Json::response($response, ['error' => 'character not found'], 404);
            }
            $member = self::withGoldDefaults($member);

            return Json::response($response, [
                'character_id' => $characterId,
                'gold' => $member['gold'],
            ], 200);
        });

        $app->post('/v1/play/campaigns/{id}/characters/{character_id}/currency/transfers', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;
            $campaignId = $args['id'];

            $characterId = $args['character_id'];
            $fromMember = $campaigns->memberByCharacterId($campaignId, $characterId);
            if ($fromMember === null) {
                return Json::response($response, ['error' => 'character not found'], 404);
            }
            $fromMember = self::withOwnerDefaults($fromMember);
            $fromMember = self::withGoldDefaults($fromMember);

            if ($fromMember['owner'] !== $actor['username']) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $body = Json::parseBody($request);
            $toCharacterId = $body['to_character_id'] ?? null;
            $gold = $body['gold'] ?? null;

            if (!is_string($toCharacterId) || $toCharacterId === '' || $toCharacterId === $characterId) {
                return Json::response($response, ['error' => 'invalid to_character_id'], 400);
            }
            $toMember = $campaigns->memberByCharacterId($campaignId, $toCharacterId);
            if ($toMember === null) {
                return Json::response($response, ['error' => 'invalid to_character_id'], 400);
            }
            $toMember = self::withGoldDefaults($toMember);

            if (!is_int($gold) || $gold < 1) {
                return Json::response($response, ['error' => 'invalid gold'], 400);
            }

            if ($fromMember['gold'] < $gold) {
                return Json::response($response, ['error' => 'insufficient gold'], 409);
            }

            $fromGold = $fromMember['gold'] - $gold;
            $toGold = $toMember['gold'] + $gold;
            $fromMember['gold'] = $fromGold;
            $toMember['gold'] = $toGold;
            $campaigns->updateMember($campaignId, $fromMember['username'], $fromMember);
            $campaigns->updateMember($campaignId, $toMember['username'], $toMember);

            $transferId = ($campaign['next_transfer_id'] ?? 1);
            $campaign['next_transfer_id'] = $transferId + 1;
            $campaigns->update($campaign);

            return Json::response($response, [
                'from_character_id' => $characterId,
                'to_character_id' => $toCharacterId,
                'gold' => $gold,
                'from_gold' => $fromGold,
                'to_gold' => $toGold,
                'transfer_id' => $transferId,
            ], 201);
        });

        $app->put('/v1/play/campaigns/{id}/characters/{character_id}/equipment/{slot}', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;
            $campaignId = $args['id'];

            $characterId = $args['character_id'];
            $member = $campaigns->memberByCharacterId($campaignId, $characterId);
            if ($member === null) {
                return Json::response($response, ['error' => 'character not found'], 404);
            }
            $member = self::withOwnerDefaults($member);
            $member = self::withInventoryDefaults($member);
            $member = self::withEquipmentDefaults($member);

            if ($member['owner'] !== $actor['username']) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $slot = $args['slot'];
            if (!array_key_exists($slot, self::EQUIPMENT_SLOTS)) {
                return Json::response($response, ['error' => 'invalid slot'], 400);
            }

            $body = Json::parseBody($request);
            $itemId = $body['item_id'] ?? null;

            if (!in_array($itemId, self::INVENTORY_ITEM_IDS, true)) {
                return Json::response($response, ['error' => 'invalid item_id'], 400);
            }

            $items = $member['inventory'];
            if (($items[$itemId] ?? 0) < 1) {
                return Json::response($response, ['error' => 'item not held'], 400);
            }

            if (self::ITEM_SLOT_MAP[$itemId] !== $slot) {
                return Json::response($response, ['error' => 'item does not match slot'], 400);
            }

            $equipment = $member['equipment'];
            $equipment[$slot] = ['item_id' => $itemId, 'attuned' => false];
            $member['equipment'] = $equipment;
            $campaigns->updateMember($campaignId, $member['username'], $member);

            return Json::response($response, [
                'character_id' => $characterId,
                'slot' => $slot,
                'item_id' => $itemId,
                'attuned' => false,
            ], 200);
        });

        $app->get('/v1/play/campaigns/{id}/characters/{character_id}/equipment/{slot}', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;
            $campaignId = $args['id'];

            $isMember = self::isOwningDm($actor, $campaign)
                || $campaigns->memberByUsername($campaignId, $actor['username']) !== null;
            if (!$isMember) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $characterId = $args['character_id'];
            $member = $campaigns->memberByCharacterId($campaignId, $characterId);
            if ($member === null) {
                return Json::response($response, ['error' => 'character not found'], 404);
            }
            $member = self::withEquipmentDefaults($member);

            $slot = $args['slot'];
            if (!array_key_exists($slot, self::EQUIPMENT_SLOTS)) {
                return Json::response($response, ['error' => 'invalid slot'], 400);
            }

            $equipped = $member['equipment'][$slot] ?? null;

            return Json::response($response, [
                'character_id' => $characterId,
                'slot' => $slot,
                'item_id' => $equipped['item_id'] ?? '',
                'attuned' => $equipped['attuned'] ?? false,
            ], 200);
        });

        $app->post('/v1/play/campaigns/{id}/characters/{character_id}/equipment/{slot}/attune', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;
            $campaignId = $args['id'];

            $characterId = $args['character_id'];
            $member = $campaigns->memberByCharacterId($campaignId, $characterId);
            if ($member === null) {
                return Json::response($response, ['error' => 'character not found'], 404);
            }
            $member = self::withOwnerDefaults($member);
            $member = self::withEquipmentDefaults($member);

            if ($member['owner'] !== $actor['username']) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $slot = $args['slot'];
            if (!array_key_exists($slot, self::EQUIPMENT_SLOTS)) {
                return Json::response($response, ['error' => 'invalid slot'], 400);
            }

            $equipment = $member['equipment'];
            $equipped = $equipment[$slot] ?? null;
            $itemId = $equipped['item_id'] ?? null;
            if ($itemId === null || !in_array($itemId, self::ATTUNABLE_ITEM_IDS, true)) {
                return Json::response($response, ['error' => 'slot does not contain an attunable item'], 400);
            }

            if ($equipped['attuned']) {
                return Json::response($response, ['error' => 'already attuned'], 409);
            }

            $attunementCount = 0;
            foreach ($equipment as $equippedSlot) {
                if (!empty($equippedSlot['attuned'])) {
                    $attunementCount++;
                }
            }
            if ($attunementCount >= self::MAX_ATTUNEMENTS) {
                return Json::response($response, ['error' => 'attunement limit reached'], 409);
            }

            $equipped['attuned'] = true;
            $equipment[$slot] = $equipped;
            $member['equipment'] = $equipment;
            $campaigns->updateMember($campaignId, $member['username'], $member);

            return Json::response($response, [
                'character_id' => $characterId,
                'slot' => $slot,
                'item_id' => $itemId,
                'attuned' => true,
                'attunement_count' => $attunementCount + 1,
                'max_attunements' => self::MAX_ATTUNEMENTS,
            ], 200);
        });

        $app->post('/v1/play/campaigns/{id}/loot', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;
            $campaignId = $args['id'];

            if (!self::isOwningDm($actor, $campaign)) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $body = Json::parseBody($request);
            $lootId = $body['loot_id'] ?? null;
            $itemId = $body['item_id'] ?? null;
            $quantity = $body['quantity'] ?? null;

            if (!is_string($lootId) || $lootId === '') {
                return Json::response($response, ['error' => 'invalid loot_id'], 400);
            }
            if (!in_array($itemId, self::INVENTORY_ITEM_IDS, true)) {
                return Json::response($response, ['error' => 'invalid item_id'], 400);
            }
            if (!is_int($quantity) || $quantity < 1) {
                return Json::response($response, ['error' => 'invalid quantity'], 400);
            }

            $loot = $campaign['loot'] ?? [];
            if (isset($loot[$lootId])) {
                return Json::response($response, ['error' => 'loot already exists'], 409);
            }

            $record = [
                'loot_id' => $lootId,
                'item_id' => $itemId,
                'quantity' => $quantity,
                'status' => 'open',
                'recipient_character_id' => null,
                'votes' => [],
            ];
            $loot[$lootId] = $record;
            $campaign['loot'] = $loot;
            $campaigns->update($campaign);

            return Json::response($response, [
                'loot_id' => $lootId,
                'item_id' => $itemId,
                'quantity' => $quantity,
                'status' => 'open',
            ], 201);
        });

        $app->post('/v1/play/campaigns/{id}/loot/{loot_id}/votes', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;
            $campaignId = $args['id'];

            if ($actor['role'] !== 'player' || $campaigns->memberByUsername($campaignId, $actor['username']) === null) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $lootId = $args['loot_id'];
            $loot = self::requireLoot($campaign, $response, $lootId);
            if ($loot instanceof Response) {
                return $loot;
            }

            $body = Json::parseBody($request);
            $recipientCharacterId = $body['recipient_character_id'] ?? null;

            if (!is_string($recipientCharacterId) || $recipientCharacterId === '') {
                return Json::response($response, ['error' => 'invalid recipient_character_id'], 400);
            }
            if ($campaigns->memberByCharacterId($campaignId, $recipientCharacterId) === null) {
                return Json::response($response, ['error' => 'invalid recipient_character_id'], 400);
            }

            $votes = $loot['votes'];
            if (isset($votes[$actor['username']])) {
                return Json::response($response, ['error' => 'already voted'], 409);
            }

            $votes[$actor['username']] = $recipientCharacterId;
            $loot['votes'] = $votes;
            $lootTable = $campaign['loot'];
            $lootTable[$lootId] = $loot;
            $campaign['loot'] = $lootTable;
            $campaigns->update($campaign);

            $votesForRecipient = count(array_filter($votes, static fn ($v) => $v === $recipientCharacterId));

            return Json::response($response, [
                'loot_id' => $lootId,
                'voter' => $actor['username'],
                'recipient_character_id' => $recipientCharacterId,
                'votes_for_recipient' => $votesForRecipient,
            ], 201);
        });

        $app->post('/v1/play/campaigns/{id}/loot/{loot_id}/assign', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;
            $campaignId = $args['id'];

            if (!self::isOwningDm($actor, $campaign)) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $lootId = $args['loot_id'];
            $loot = self::requireLoot($campaign, $response, $lootId);
            if ($loot instanceof Response) {
                return $loot;
            }

            if ($loot['status'] !== 'open') {
                return Json::response($response, ['error' => 'loot not open'], 409);
            }

            $tally = [];
            foreach ($loot['votes'] as $recipientCharacterId) {
                $tally[$recipientCharacterId] = ($tally[$recipientCharacterId] ?? 0) + 1;
            }
            if (empty($tally)) {
                return Json::response($response, ['error' => 'no votes cast'], 409);
            }

            $maxVotes = max($tally);
            $topRecipients = array_keys(array_filter($tally, static fn ($count) => $count === $maxVotes));
            if (count($topRecipients) !== 1) {
                return Json::response($response, ['error' => 'tied vote'], 409);
            }

            $recipientCharacterId = $topRecipients[0];
            $recipient = $campaigns->memberByCharacterId($campaignId, $recipientCharacterId);
            if ($recipient === null) {
                return Json::response($response, ['error' => 'recipient not found'], 409);
            }
            $recipient = self::withInventoryDefaults($recipient);

            $items = $recipient['inventory'];
            $items[$loot['item_id']] = ($items[$loot['item_id']] ?? 0) + $loot['quantity'];
            $recipient['inventory'] = $items;
            $campaigns->updateMember($campaignId, $recipient['username'], $recipient);

            $loot['status'] = 'assigned';
            $loot['recipient_character_id'] = $recipientCharacterId;
            $lootTable = $campaign['loot'];
            $lootTable[$lootId] = $loot;
            $campaign['loot'] = $lootTable;
            $campaigns->update($campaign);

            return Json::response($response, [
                'loot_id' => $lootId,
                'recipient_character_id' => $recipientCharacterId,
                'item_id' => $loot['item_id'],
                'quantity' => $loot['quantity'],
                'votes' => $maxVotes,
                'status' => 'assigned',
            ], 200);
        });

        $app->get('/v1/play/campaigns/{id}/loot/{loot_id}', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;
            $campaignId = $args['id'];

            $isMember = self::isOwningDm($actor, $campaign)
                || $campaigns->memberByUsername($campaignId, $actor['username']) !== null;
            if (!$isMember) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $lootId = $args['loot_id'];
            $loot = self::requireLoot($campaign, $response, $lootId);
            if ($loot instanceof Response) {
                return $loot;
            }

            $tally = [];
            foreach ($loot['votes'] as $recipientCharacterId) {
                $tally[$recipientCharacterId] = ($tally[$recipientCharacterId] ?? 0) + 1;
            }

            return Json::response($response, [
                'loot_id' => $loot['loot_id'],
                'item_id' => $loot['item_id'],
                'quantity' => $loot['quantity'],
                'status' => $loot['status'],
                'recipient_character_id' => $loot['recipient_character_id'],
                'votes' => empty($tally) ? new \stdClass() : $tally,
            ], 200);
        });

        $app->post('/v1/play/campaigns/{id}/npcs', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;

            if (!self::isOwningDm($actor, $campaign)) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $body = Json::parseBody($request);
            $npcId = $body['npc_id'] ?? null;
            $name = $body['name'] ?? null;
            $agenda = $body['agenda'] ?? null;
            $publicStatus = $body['public_status'] ?? null;

            if (!is_string($npcId) || $npcId === '') {
                return Json::response($response, ['error' => 'invalid npc_id'], 400);
            }
            if (!is_string($name) || $name === '') {
                return Json::response($response, ['error' => 'invalid name'], 400);
            }
            if (!is_string($agenda) || $agenda === '') {
                return Json::response($response, ['error' => 'invalid agenda'], 400);
            }
            if (!is_string($publicStatus) || $publicStatus === '') {
                return Json::response($response, ['error' => 'invalid public_status'], 400);
            }

            $npcs = $campaign['npcs'] ?? [];
            if (isset($npcs[$npcId])) {
                return Json::response($response, ['error' => 'npc already exists'], 409);
            }

            $record = [
                'npc_id' => $npcId,
                'name' => $name,
                'agenda' => $agenda,
                'public_status' => $publicStatus,
            ];
            $npcs[$npcId] = $record;
            $campaign['npcs'] = $npcs;
            $campaigns->update($campaign);

            return Json::response($response, $record, 201);
        });

        $app->put('/v1/play/campaigns/{id}/npcs/{npc_id}/agenda', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;

            if (!self::isOwningDm($actor, $campaign)) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $npcId = $args['npc_id'];
            $npc = self::requireNpc($campaign, $response, $npcId);
            if ($npc instanceof Response) {
                return $npc;
            }

            $body = Json::parseBody($request);
            $agenda = $body['agenda'] ?? null;
            $publicStatus = $body['public_status'] ?? null;

            if (!is_string($agenda) || $agenda === '') {
                return Json::response($response, ['error' => 'invalid agenda'], 400);
            }
            if (!is_string($publicStatus) || $publicStatus === '') {
                return Json::response($response, ['error' => 'invalid public_status'], 400);
            }

            $npc['agenda'] = $agenda;
            $npc['public_status'] = $publicStatus;
            $npcs = $campaign['npcs'];
            $npcs[$npcId] = $npc;
            $campaign['npcs'] = $npcs;
            $campaigns->update($campaign);

            return Json::response($response, $npc, 200);
        });

        $app->get('/v1/play/campaigns/{id}/npcs/{npc_id}', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;
            $campaignId = $args['id'];

            $isDm = self::isOwningDm($actor, $campaign);
            $isMember = $isDm || $campaigns->memberByUsername($campaignId, $actor['username']) !== null;
            if (!$isMember) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $npcId = $args['npc_id'];
            $npc = self::requireNpc($campaign, $response, $npcId);
            if ($npc instanceof Response) {
                return $npc;
            }

            if ($isDm) {
                return Json::response($response, $npc, 200);
            }

            return Json::response($response, [
                'npc_id' => $npc['npc_id'],
                'name' => $npc['name'],
                'public_status' => $npc['public_status'],
            ], 200);
        });

        $app->post('/v1/play/campaigns/{id}/factions', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;

            if (!self::isOwningDm($actor, $campaign)) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $body = Json::parseBody($request);
            $factionId = $body['faction_id'] ?? null;
            $name = $body['name'] ?? null;

            if (!is_string($factionId) || $factionId === '') {
                return Json::response($response, ['error' => 'invalid faction_id'], 400);
            }
            if (!is_string($name) || $name === '') {
                return Json::response($response, ['error' => 'invalid name'], 400);
            }

            $factions = $campaign['factions'] ?? [];
            if (isset($factions[$factionId])) {
                return Json::response($response, ['error' => 'faction already exists'], 409);
            }

            $record = [
                'faction_id' => $factionId,
                'name' => $name,
            ];
            $factions[$factionId] = $record;
            $campaign['factions'] = $factions;
            $campaigns->update($campaign);

            return Json::response($response, $record, 201);
        });

        $app->post('/v1/play/campaigns/{id}/factions/{faction_id}/reputation', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;
            $campaignId = $args['id'];

            if (!self::isOwningDm($actor, $campaign)) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $factionId = $args['faction_id'];
            $faction = self::requireFaction($campaign, $response, $factionId);
            if ($faction instanceof Response) {
                return $faction;
            }

            $body = Json::parseBody($request);
            $characterId = $body['character_id'] ?? null;
            $delta = $body['delta'] ?? null;
            $reason = $body['reason'] ?? null;

            if (!is_string($characterId) || $characterId === '') {
                return Json::response($response, ['error' => 'invalid character_id'], 400);
            }
            if ($campaigns->memberByCharacterId($campaignId, $characterId) === null) {
                return Json::response($response, ['error' => 'invalid character_id'], 400);
            }
            if (!is_int($delta) || $delta === 0 || $delta < -25 || $delta > 25) {
                return Json::response($response, ['error' => 'invalid delta'], 400);
            }
            if (!is_string($reason) || $reason === '') {
                return Json::response($response, ['error' => 'invalid reason'], 400);
            }

            $reputations = $campaign['faction_reputations'] ?? [];
            $key = $factionId . '::' . $characterId;
            $current = $reputations[$key] ?? 0;
            $updated = max(-100, min(100, $current + $delta));
            $reputations[$key] = $updated;
            $campaign['faction_reputations'] = $reputations;

            $entry = [
                'faction_id' => $factionId,
                'character_id' => $characterId,
                'reputation' => $updated,
                'delta' => $delta,
                'reason' => $reason,
            ];

            $history = $campaign['faction_reputation_history'] ?? [];
            $history[] = $entry;
            $campaign['faction_reputation_history'] = $history;

            $campaigns->update($campaign);

            return Json::response($response, $entry, 201);
        });

        $app->get('/v1/play/campaigns/{id}/factions/{faction_id}/reputation', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;
            $campaignId = $args['id'];

            $isDm = self::isOwningDm($actor, $campaign);
            $member = $campaigns->memberByUsername($campaignId, $actor['username']);
            if (!$isDm && $member === null) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $factionId = $args['faction_id'];
            $faction = self::requireFaction($campaign, $response, $factionId);
            if ($faction instanceof Response) {
                return $faction;
            }

            $history = $campaign['faction_reputation_history'] ?? [];
            $entries = array_values(array_filter(
                $history,
                static fn (array $entry) => $entry['faction_id'] === $factionId
            ));

            if (!$isDm) {
                $ownCharacterId = $member['character_id'];
                $entries = array_values(array_filter(
                    $entries,
                    static fn (array $entry) => $entry['character_id'] === $ownCharacterId
                ));
            }

            return Json::response($response, [
                'faction_id' => $factionId,
                'entries' => $entries,
            ], 200);
        });

        $app->post('/v1/play/campaigns/{id}/npcs/{npc_id}/dialogue', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;

            $npcId = $args['npc_id'];
            $npc = self::requireNpc($campaign, $response, $npcId);
            if ($npc instanceof Response) {
                return $npc;
            }

            if (!self::isOwningDm($actor, $campaign)) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $body = Json::parseBody($request);
            $dialogueId = $body['dialogue_id'] ?? null;
            $speaker = $body['speaker'] ?? null;
            $text = $body['text'] ?? null;
            $visibility = $body['visibility'] ?? null;

            if (!is_string($dialogueId) || $dialogueId === '') {
                return Json::response($response, ['error' => 'invalid dialogue_id'], 400);
            }
            if (!is_string($speaker) || $speaker === '') {
                return Json::response($response, ['error' => 'invalid speaker'], 400);
            }
            if (!is_string($text) || $text === '') {
                return Json::response($response, ['error' => 'invalid text'], 400);
            }
            if ($visibility !== 'public' && $visibility !== 'private') {
                return Json::response($response, ['error' => 'invalid visibility'], 400);
            }

            $dialogue = $npc['dialogue'] ?? [];
            foreach ($dialogue as $entry) {
                if ($entry['dialogue_id'] === $dialogueId) {
                    return Json::response($response, ['error' => 'dialogue already exists'], 409);
                }
            }

            $entry = [
                'dialogue_id' => $dialogueId,
                'speaker' => $speaker,
                'text' => $text,
                'visibility' => $visibility,
            ];
            $dialogue[] = $entry;
            $npc['dialogue'] = $dialogue;
            $npcs = $campaign['npcs'];
            $npcs[$npcId] = $npc;
            $campaign['npcs'] = $npcs;
            $campaigns->update($campaign);

            return Json::response($response, $entry, 201);
        });

        $app->get('/v1/play/campaigns/{id}/npcs/{npc_id}/dialogue', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;
            $campaignId = $args['id'];

            $isDm = self::isOwningDm($actor, $campaign);
            $isMember = $isDm || $campaigns->memberByUsername($campaignId, $actor['username']) !== null;
            if (!$isMember) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $npcId = $args['npc_id'];
            $npc = self::requireNpc($campaign, $response, $npcId);
            if ($npc instanceof Response) {
                return $npc;
            }

            $entries = $npc['dialogue'] ?? [];
            if (!$isDm) {
                $entries = array_values(array_filter(
                    $entries,
                    static fn (array $entry) => $entry['visibility'] === 'public'
                ));
            }

            return Json::response($response, [
                'npc_id' => $npcId,
                'entries' => $entries,
            ], 200);
        });

        $app->post('/v1/play/campaigns/{id}/relationships', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;
            $campaignId = $args['id'];

            if (!self::isOwningDm($actor, $campaign)) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $body = Json::parseBody($request);
            $sourceId = $body['source_id'] ?? null;
            $targetId = $body['target_id'] ?? null;
            $kind = $body['kind'] ?? null;
            $score = $body['score'] ?? null;

            if (!is_string($sourceId) || $sourceId === '' || !is_string($targetId) || $targetId === '') {
                return Json::response($response, ['error' => 'invalid entity id'], 400);
            }
            if ($sourceId === $targetId) {
                return Json::response($response, ['error' => 'source_id and target_id must differ'], 400);
            }
            if (!is_string($kind) || $kind === '') {
                return Json::response($response, ['error' => 'invalid kind'], 400);
            }
            if (!is_int($score) || $score < -100 || $score > 100) {
                return Json::response($response, ['error' => 'invalid score'], 400);
            }

            if (!self::campaignEntityExists($campaigns, $campaign, $campaignId, $sourceId)) {
                return Json::response($response, ['error' => 'unknown entity: ' . $sourceId], 404);
            }
            if (!self::campaignEntityExists($campaigns, $campaign, $campaignId, $targetId)) {
                return Json::response($response, ['error' => 'unknown entity: ' . $targetId], 404);
            }

            $relationships = $campaign['relationships'] ?? [];
            foreach ($relationships as $edge) {
                if ($edge['source_id'] === $sourceId && $edge['target_id'] === $targetId && $edge['kind'] === $kind) {
                    return Json::response($response, ['error' => 'relationship already exists'], 409);
                }
            }

            $edge = [
                'source_id' => $sourceId,
                'target_id' => $targetId,
                'kind' => $kind,
                'score' => $score,
            ];
            $relationships[] = $edge;
            $campaign['relationships'] = $relationships;
            $campaigns->update($campaign);

            return Json::response($response, $edge, 201);
        });

        $app->put('/v1/play/campaigns/{id}/relationships/{source_id}/{target_id}/{kind}', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;

            if (!self::isOwningDm($actor, $campaign)) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $sourceId = $args['source_id'];
            $targetId = $args['target_id'];
            $kind = $args['kind'];

            $body = Json::parseBody($request);
            $score = $body['score'] ?? null;
            if (!is_int($score) || $score < -100 || $score > 100) {
                return Json::response($response, ['error' => 'invalid score'], 400);
            }

            $relationships = $campaign['relationships'] ?? [];
            $found = false;
            foreach ($relationships as $index => $edge) {
                if ($edge['source_id'] === $sourceId && $edge['target_id'] === $targetId && $edge['kind'] === $kind) {
                    $relationships[$index]['score'] = $score;
                    $found = true;
                    $updated = $relationships[$index];
                    break;
                }
            }

            if (!$found) {
                return Json::response($response, ['error' => 'relationship not found'], 404);
            }

            $campaign['relationships'] = $relationships;
            $campaigns->update($campaign);

            return Json::response($response, $updated, 200);
        });

        $app->get('/v1/play/campaigns/{id}/relationships', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;
            $campaignId = $args['id'];

            $isDm = self::isOwningDm($actor, $campaign);
            $isMember = $isDm || $campaigns->memberByUsername($campaignId, $actor['username']) !== null;
            if (!$isMember) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $edges = $campaign['relationships'] ?? [];

            return Json::response($response, ['edges' => $edges], 200);
        });

        $app->post('/v1/play/campaigns/{id}/clues', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;
            $campaignId = $args['id'];

            if (!self::isOwningDm($actor, $campaign)) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $body = Json::parseBody($request);
            $clueId = $body['clue_id'] ?? null;
            $text = $body['text'] ?? null;
            $audience = $body['audience'] ?? null;
            $characterId = $body['character_id'] ?? null;

            if (!is_string($clueId) || $clueId === '') {
                return Json::response($response, ['error' => 'invalid clue_id'], 400);
            }
            if (!is_string($text) || $text === '') {
                return Json::response($response, ['error' => 'invalid text'], 400);
            }
            if (!in_array($audience, ['character', 'party', 'hidden'], true)) {
                return Json::response($response, ['error' => 'invalid audience'], 400);
            }

            if ($audience === 'character') {
                if (!is_string($characterId) || $characterId === '') {
                    return Json::response($response, ['error' => 'character_id required'], 400);
                }
                if (!$campaigns->characterIdExists($campaignId, $characterId)) {
                    return Json::response($response, ['error' => 'unknown character: ' . $characterId], 400);
                }
            } else {
                if ($characterId !== null) {
                    return Json::response($response, ['error' => 'character_id must be omitted'], 400);
                }
            }

            $clues = $campaign['clues'] ?? [];
            foreach ($clues as $clue) {
                if ($clue['clue_id'] === $clueId) {
                    return Json::response($response, ['error' => 'clue already exists'], 409);
                }
            }

            $clue = [
                'clue_id' => $clueId,
                'text' => $text,
                'audience' => $audience,
            ];
            if ($audience === 'character') {
                $clue['character_id'] = $characterId;
            }

            $clues[] = $clue;
            $campaign['clues'] = $clues;
            $campaigns->update($campaign);

            return Json::response($response, $clue, 201);
        });

        $app->get('/v1/play/campaigns/{id}/clues', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;
            $campaignId = $args['id'];

            $isDm = self::isOwningDm($actor, $campaign);
            $member = $isDm ? null : $campaigns->memberByUsername($campaignId, $actor['username']);
            if (!$isDm && $member === null) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $clues = $campaign['clues'] ?? [];
            if (!$isDm) {
                $ownCharacterId = $member['character_id'];
                $clues = array_values(array_filter(
                    $clues,
                    static fn (array $clue) => $clue['audience'] === 'party'
                        || ($clue['audience'] === 'character' && $clue['character_id'] === $ownCharacterId)
                ));
            }

            return Json::response($response, ['clues' => $clues], 200);
        });

        $app->post('/v1/play/campaigns/{id}/quests', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;
            $campaignId = $args['id'];

            if (!self::isOwningDm($actor, $campaign)) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $body = Json::parseBody($request);
            $questId = $body['quest_id'] ?? null;
            $title = $body['title'] ?? null;
            $dependsOn = $body['depends_on'] ?? null;

            if (!is_string($questId) || $questId === '') {
                return Json::response($response, ['error' => 'invalid quest_id'], 400);
            }
            if (!is_string($title) || $title === '') {
                return Json::response($response, ['error' => 'invalid title'], 400);
            }
            if (!is_array($dependsOn) || !array_is_list($dependsOn)) {
                return Json::response($response, ['error' => 'invalid depends_on'], 400);
            }
            foreach ($dependsOn as $dep) {
                if (!is_string($dep) || $dep === '') {
                    return Json::response($response, ['error' => 'invalid depends_on'], 400);
                }
            }
            if (count($dependsOn) !== count(array_unique($dependsOn))) {
                return Json::response($response, ['error' => 'invalid depends_on'], 400);
            }
            if (in_array($questId, $dependsOn, true)) {
                return Json::response($response, ['error' => 'invalid depends_on'], 400);
            }

            $quests = $campaign['quests'] ?? [];
            $existingIds = array_column($quests, 'quest_id');

            foreach ($dependsOn as $dep) {
                if (!in_array($dep, $existingIds, true)) {
                    return Json::response($response, ['error' => 'unknown dependency: ' . $dep], 400);
                }
            }

            if (in_array($questId, $existingIds, true)) {
                return Json::response($response, ['error' => 'quest already exists'], 409);
            }

            $quest = [
                'quest_id' => $questId,
                'title' => $title,
                'depends_on' => array_values($dependsOn),
                'state' => 'locked',
            ];

            $quests[] = $quest;
            $campaign['quests'] = $quests;
            $campaigns->update($campaign);

            return Json::response($response, $quest, 201);
        });

        $app->put('/v1/play/campaigns/{id}/quests/{quest_id}/state', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;
            $campaignId = $args['id'];
            $questId = $args['quest_id'];

            if (!self::isOwningDm($actor, $campaign)) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $quests = $campaign['quests'] ?? [];
            $index = null;
            foreach ($quests as $i => $quest) {
                if ($quest['quest_id'] === $questId) {
                    $index = $i;
                    break;
                }
            }
            if ($index === null) {
                return Json::response($response, ['error' => 'quest not found'], 404);
            }

            $body = Json::parseBody($request);
            $state = $body['state'] ?? null;
            if (!in_array($state, ['active', 'completed'], true)) {
                return Json::response($response, ['error' => 'invalid state'], 400);
            }

            $quest = $quests[$index];
            $currentState = $quest['state'];

            if ($state === 'active') {
                if ($currentState !== 'locked') {
                    return Json::response($response, ['error' => 'invalid transition'], 409);
                }
                $questsById = [];
                foreach ($quests as $q) {
                    $questsById[$q['quest_id']] = $q;
                }
                foreach ($quest['depends_on'] as $dep) {
                    if (($questsById[$dep]['state'] ?? null) !== 'completed') {
                        return Json::response($response, ['error' => 'invalid transition'], 409);
                    }
                }
            } elseif ($state === 'completed') {
                if ($currentState !== 'active') {
                    return Json::response($response, ['error' => 'invalid transition'], 409);
                }
            }

            $quest['state'] = $state;
            $quests[$index] = $quest;
            $campaign['quests'] = $quests;
            $campaigns->update($campaign);

            return Json::response($response, $quest, 200);
        });

        $app->get('/v1/play/campaigns/{id}/quests', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;
            $campaignId = $args['id'];

            $isDm = self::isOwningDm($actor, $campaign);
            $isMember = $isDm || $campaigns->memberByUsername($campaignId, $actor['username']) !== null;
            if (!$isMember) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $quests = $campaign['quests'] ?? [];

            return Json::response($response, ['quests' => $quests], 200);
        });

        $app->put('/v1/play/campaigns/{id}/quests/{quest_id}/rewards', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;
            $campaignId = $args['id'];
            $questId = $args['quest_id'];

            if (!self::isOwningDm($actor, $campaign)) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $quests = $campaign['quests'] ?? [];
            $index = null;
            foreach ($quests as $i => $quest) {
                if ($quest['quest_id'] === $questId) {
                    $index = $i;
                    break;
                }
            }
            if ($index === null) {
                return Json::response($response, ['error' => 'quest not found'], 404);
            }

            $quest = $quests[$index];
            if ($quest['state'] === 'completed') {
                return Json::response($response, ['error' => 'quest already completed'], 409);
            }

            $body = Json::parseBody($request);
            $xp = $body['xp'] ?? null;
            $items = $body['items'] ?? null;

            if (!is_int($xp) || $xp < 0) {
                return Json::response($response, ['error' => 'invalid xp'], 400);
            }
            if (!is_array($items) || (array_is_list($items) && count($items) > 0)) {
                return Json::response($response, ['error' => 'invalid items'], 400);
            }

            $normalizedItems = [];
            foreach ($items as $itemId => $quantity) {
                if (!is_string($itemId) || !in_array($itemId, self::INVENTORY_ITEM_IDS, true)) {
                    return Json::response($response, ['error' => 'invalid items'], 400);
                }
                if (!is_int($quantity) || $quantity < 1) {
                    return Json::response($response, ['error' => 'invalid items'], 400);
                }
                $normalizedItems[$itemId] = $quantity;
            }

            $quest['rewards'] = ['xp' => $xp, 'items' => $normalizedItems];
            $quests[$index] = $quest;
            $campaign['quests'] = $quests;
            $campaigns->update($campaign);

            return Json::response($response, $quest, 200);
        });

        $app->post('/v1/play/campaigns/{id}/quests/{quest_id}/rewards/award', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;
            $campaignId = $args['id'];
            $questId = $args['quest_id'];

            if (!self::isOwningDm($actor, $campaign)) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $quests = $campaign['quests'] ?? [];
            $index = null;
            foreach ($quests as $i => $quest) {
                if ($quest['quest_id'] === $questId) {
                    $index = $i;
                    break;
                }
            }
            if ($index === null) {
                return Json::response($response, ['error' => 'quest not found'], 404);
            }

            $quest = $quests[$index];
            if ($quest['state'] !== 'completed' || !isset($quest['rewards'])) {
                return Json::response($response, ['error' => 'rewards not available'], 409);
            }
            if ($quest['rewards']['awarded'] ?? false) {
                return Json::response($response, ['error' => 'rewards already awarded'], 409);
            }

            $xp = $quest['rewards']['xp'];
            $items = $quest['rewards']['items'];

            foreach ($campaigns->membersInJoinOrder($campaignId) as $member) {
                $member = self::withQuestRewardDefaults($member);
                $member = self::withInventoryDefaults($member);
                $member['quest_rewards']['xp'] += $xp;
                foreach ($items as $itemId => $quantity) {
                    $member['quest_rewards']['items'][$itemId] = ($member['quest_rewards']['items'][$itemId] ?? 0) + $quantity;
                    $member['inventory'][$itemId] = ($member['inventory'][$itemId] ?? 0) + $quantity;
                }
                $campaigns->updateMember($campaignId, $member['username'], $member);
            }

            $quest['rewards']['awarded'] = true;
            $quests[$index] = $quest;
            $campaign['quests'] = $quests;
            $campaigns->update($campaign);

            return Json::response($response, [
                'quest_id' => $questId,
                'awarded' => true,
                'xp' => $xp,
                'items' => $items,
            ], 201);
        });

        $app->get('/v1/play/campaigns/{id}/characters/{character_id}/rewards', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;
            $campaignId = $args['id'];

            $isMember = self::isOwningDm($actor, $campaign)
                || $campaigns->memberByUsername($campaignId, $actor['username']) !== null;
            if (!$isMember) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $characterId = $args['character_id'];
            $member = $campaigns->memberByCharacterId($campaignId, $characterId);
            if ($member === null) {
                return Json::response($response, ['error' => 'character not found'], 404);
            }
            $member = self::withQuestRewardDefaults($member);

            return Json::response($response, [
                'character_id' => $characterId,
                'xp' => $member['quest_rewards']['xp'],
                'items' => $member['quest_rewards']['items'],
            ], 200);
        });

        $app->post('/v1/play/campaigns/{id}/world-events', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;
            $campaignId = $args['id'];

            if (!self::isOwningDm($actor, $campaign)) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $body = Json::parseBody($request);
            $eventId = $body['event_id'] ?? null;
            $turnNumber = $body['turn_number'] ?? null;
            $title = $body['title'] ?? null;
            $text = $body['text'] ?? null;

            if (!is_string($eventId) || $eventId === ''
                || !is_string($title) || $title === ''
                || !is_string($text) || $text === ''
                || !is_int($turnNumber)
            ) {
                return Json::response($response, ['error' => 'invalid body'], 400);
            }

            $currentTurn = $campaign['turn_number'] ?? 1;
            if ($turnNumber < $currentTurn) {
                return Json::response($response, ['error' => 'invalid body'], 400);
            }

            $worldEvents = $campaign['world_events'] ?? [];
            foreach ($worldEvents as $existing) {
                if ($existing['event_id'] === $eventId) {
                    return Json::response($response, ['error' => 'duplicate event id'], 409);
                }
            }

            $event = [
                'event_id' => $eventId,
                'turn_number' => $turnNumber,
                'title' => $title,
                'text' => $text,
                'status' => 'scheduled',
            ];

            $worldEvents[] = $event;
            $campaign['world_events'] = $worldEvents;
            $campaigns->update($campaign);

            return Json::response($response, $event, 201);
        });

        $app->post('/v1/play/campaigns/{id}/world-events/{event_id}/resolve', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;
            $campaignId = $args['id'];
            $eventId = $args['event_id'];

            if (!self::isOwningDm($actor, $campaign)) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $worldEvents = $campaign['world_events'] ?? [];
            $index = null;
            foreach ($worldEvents as $i => $existing) {
                if ($existing['event_id'] === $eventId) {
                    $index = $i;
                    break;
                }
            }
            if ($index === null) {
                return Json::response($response, ['error' => 'event not found'], 404);
            }

            $body = Json::parseBody($request);
            $text = $body['text'] ?? null;
            if (!is_string($text) || $text === '') {
                return Json::response($response, ['error' => 'invalid body'], 400);
            }

            $event = $worldEvents[$index];

            if ($event['status'] === 'resolved') {
                return Json::response($response, ['error' => 'already resolved'], 409);
            }

            $currentTurn = $campaign['turn_number'] ?? 1;
            if ($currentTurn !== $event['turn_number']) {
                return Json::response($response, ['error' => 'turn mismatch'], 409);
            }

            $event['status'] = 'resolved';
            $event['resolution'] = [
                'turn_number' => $event['turn_number'],
                'text' => $text,
            ];

            $worldEvents[$index] = $event;
            $campaign['world_events'] = $worldEvents;
            $campaigns->update($campaign);

            return Json::response($response, $event, 201);
        });

        $app->get('/v1/play/campaigns/{id}/world-events', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;
            $campaignId = $args['id'];

            $isMember = self::isOwningDm($actor, $campaign)
                || $campaigns->memberByUsername($campaignId, $actor['username']) !== null;
            if (!$isMember) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $worldEvents = $campaign['world_events'] ?? [];
            usort($worldEvents, static function (array $a, array $b) {
                return $a['turn_number'] <=> $b['turn_number'];
            });

            return Json::response($response, ['events' => array_values($worldEvents)], 200);
        });

        $app->post('/v1/play/campaigns/{id}/calendar', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;

            if (!self::isOwningDm($actor, $campaign)) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $body = Json::parseBody($request);
            $day = $body['day'] ?? null;
            $season = $body['season'] ?? null;

            if (!is_int($day) || $day < 1) {
                return Json::response($response, ['error' => 'invalid day'], 400);
            }
            if (!is_string($season) || !isset(self::SEASON_OFFSETS[$season])) {
                return Json::response($response, ['error' => 'invalid season'], 400);
            }

            if (isset($campaign['calendar'])) {
                return Json::response($response, ['error' => 'calendar already initialized'], 409);
            }

            $calendar = ['day' => $day, 'season' => $season];
            $campaign['calendar'] = $calendar;
            $campaigns->update($campaign);

            return Json::response($response, self::calendarView($calendar), 201);
        });

        $app->get('/v1/play/campaigns/{id}/calendar', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;
            $campaignId = $args['id'];

            $isMember = self::isOwningDm($actor, $campaign)
                || $campaigns->memberByUsername($campaignId, $actor['username']) !== null;
            if (!$isMember) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $calendar = $campaign['calendar'] ?? null;
            if ($calendar === null) {
                return Json::response($response, ['error' => 'calendar not initialized'], 404);
            }

            return Json::response($response, self::calendarView($calendar), 200);
        });

        $app->post('/v1/play/campaigns/{id}/calendar/advance', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;

            if (!self::isOwningDm($actor, $campaign)) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $body = Json::parseBody($request);
            $days = $body['days'] ?? null;

            if (!is_int($days) || $days < 1 || $days > 30) {
                return Json::response($response, ['error' => 'invalid days'], 400);
            }

            $calendar = $campaign['calendar'] ?? null;
            if ($calendar === null) {
                return Json::response($response, ['error' => 'calendar not initialized'], 404);
            }

            $calendar['day'] += $days;
            $campaign['calendar'] = $calendar;
            $campaigns->update($campaign);

            return Json::response($response, self::calendarView($calendar), 200);
        });

        $app->post('/v1/play/campaigns/{id}/settlements', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;
            $campaignId = $args['id'];

            if (!self::isOwningDm($actor, $campaign)) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $body = Json::parseBody($request);
            $settlementId = $body['settlement_id'] ?? null;
            $name = $body['name'] ?? null;
            $services = $body['services'] ?? null;
            $availability = $body['availability'] ?? null;

            if (!is_string($settlementId) || $settlementId === '') {
                return Json::response($response, ['error' => 'invalid settlement_id'], 400);
            }
            if (!is_string($name) || $name === '') {
                return Json::response($response, ['error' => 'invalid name'], 400);
            }
            $normalizedServices = self::normalizeServices($services);
            if ($normalizedServices === null) {
                return Json::response($response, ['error' => 'invalid services'], 400);
            }
            if (!in_array($availability, ['open', 'limited', 'closed'], true)) {
                return Json::response($response, ['error' => 'invalid availability'], 400);
            }

            $settlements = $campaign['settlements'] ?? [];
            if (isset($settlements[$settlementId])) {
                return Json::response($response, ['error' => 'settlement already exists'], 409);
            }

            $settlement = [
                'settlement_id' => $settlementId,
                'name' => $name,
                'services' => $normalizedServices,
                'availability' => $availability,
                'discovered_by' => [],
            ];
            $settlements[$settlementId] = $settlement;
            $campaign['settlements'] = $settlements;
            $campaigns->update($campaign);

            return Json::response($response, $settlement, 201);
        });

        $app->put('/v1/play/campaigns/{id}/settlements/{settlement_id}', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;

            if (!self::isOwningDm($actor, $campaign)) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $settlementId = $args['settlement_id'];
            $settlements = $campaign['settlements'] ?? [];
            $settlement = $settlements[$settlementId] ?? null;
            if ($settlement === null) {
                return Json::response($response, ['error' => 'settlement not found'], 404);
            }

            $body = Json::parseBody($request);
            $name = $body['name'] ?? null;
            $services = $body['services'] ?? null;
            $availability = $body['availability'] ?? null;

            if (!is_string($name) || $name === '') {
                return Json::response($response, ['error' => 'invalid name'], 400);
            }
            $normalizedServices = self::normalizeServices($services);
            if ($normalizedServices === null) {
                return Json::response($response, ['error' => 'invalid services'], 400);
            }
            if (!in_array($availability, ['open', 'limited', 'closed'], true)) {
                return Json::response($response, ['error' => 'invalid availability'], 400);
            }

            $settlement['name'] = $name;
            $settlement['services'] = $normalizedServices;
            $settlement['availability'] = $availability;
            $settlements[$settlementId] = $settlement;
            $campaign['settlements'] = $settlements;
            $campaigns->update($campaign);

            return Json::response($response, $settlement, 200);
        });

        $app->post('/v1/play/campaigns/{id}/settlements/{settlement_id}/discover', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;
            $campaignId = $args['id'];

            if ($actor['role'] !== 'player') {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }
            $member = $campaigns->memberByUsername($campaignId, $actor['username']);
            if ($member === null) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $settlementId = $args['settlement_id'];
            $settlements = $campaign['settlements'] ?? [];
            $settlement = $settlements[$settlementId] ?? null;
            if ($settlement === null) {
                return Json::response($response, ['error' => 'settlement not found'], 404);
            }

            $characterId = $member['character_id'];
            $status = 201;
            if (in_array($characterId, $settlement['discovered_by'], true)) {
                $status = 200;
            } else {
                $settlement['discovered_by'][] = $characterId;
                $settlements[$settlementId] = $settlement;
                $campaign['settlements'] = $settlements;
                $campaigns->update($campaign);
            }

            return Json::response($response, self::playerSettlementView($settlement, $characterId), $status);
        });

        $app->get('/v1/play/campaigns/{id}/settlements', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;
            $campaignId = $args['id'];

            $isDm = self::isOwningDm($actor, $campaign);
            $member = $isDm ? null : $campaigns->memberByUsername($campaignId, $actor['username']);
            if (!$isDm && $member === null) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $settlements = array_values($campaign['settlements'] ?? []);

            if ($isDm) {
                return Json::response($response, ['settlements' => $settlements], 200);
            }

            $characterId = $member['character_id'];
            $result = [];
            foreach ($settlements as $settlement) {
                if (in_array($characterId, $settlement['discovered_by'], true)) {
                    $result[] = self::playerSettlementView($settlement, $characterId);
                }
            }

            return Json::response($response, ['settlements' => $result], 200);
        });

        $app->post('/v1/play/campaigns/{id}/settlements/{settlement_id}/shops', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;

            if (!self::isOwningDm($actor, $campaign)) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $settlementId = $args['settlement_id'];
            $settlements = $campaign['settlements'] ?? [];
            $settlement = $settlements[$settlementId] ?? null;
            if ($settlement === null) {
                return Json::response($response, ['error' => 'settlement not found'], 404);
            }

            $body = Json::parseBody($request);
            $shop = self::normalizeShop($body);
            if ($shop === null) {
                return Json::response($response, ['error' => 'invalid shop'], 400);
            }

            $shops = $settlement['shops'] ?? [];
            if (isset($shops[$shop['shop_id']])) {
                return Json::response($response, ['error' => 'shop already exists'], 409);
            }

            $shops[$shop['shop_id']] = $shop;
            $settlement['shops'] = $shops;
            $settlements[$settlementId] = $settlement;
            $campaign['settlements'] = $settlements;
            $campaigns->update($campaign);

            return Json::response($response, $shop, 201);
        });

        $app->get('/v1/play/campaigns/{id}/settlements/{settlement_id}/shops/{shop_id}', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;
            $campaignId = $args['id'];

            $isDm = self::isOwningDm($actor, $campaign);
            $member = $isDm ? null : $campaigns->memberByUsername($campaignId, $actor['username']);
            if (!$isDm && $member === null) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $settlementId = $args['settlement_id'];
            $settlements = $campaign['settlements'] ?? [];
            $settlement = $settlements[$settlementId] ?? null;
            if ($settlement === null) {
                return Json::response($response, ['error' => 'settlement not found'], 404);
            }

            if (!$isDm && !in_array($member['character_id'], $settlement['discovered_by'], true)) {
                return Json::response($response, ['error' => 'settlement not found'], 404);
            }

            $shopId = $args['shop_id'];
            $shops = $settlement['shops'] ?? [];
            $shop = $shops[$shopId] ?? null;
            if ($shop === null) {
                return Json::response($response, ['error' => 'shop not found'], 404);
            }

            return Json::response($response, $shop, 200);
        });

        $app->post('/v1/play/campaigns/{id}/settlements/{settlement_id}/shops/{shop_id}/buy', function (Request $request, Response $response, array $args) use ($dbFile) {
            return self::handleShopTrade($request, $response, $args, $dbFile, 'buy');
        });

        $app->post('/v1/play/campaigns/{id}/settlements/{settlement_id}/shops/{shop_id}/sell', function (Request $request, Response $response, array $args) use ($dbFile) {
            return self::handleShopTrade($request, $response, $args, $dbFile, 'sell');
        });

        $app->post('/v1/play/campaigns/{id}/recipes', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;

            if (!self::isOwningDm($actor, $campaign)) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $body = Json::parseBody($request);
            $recipe = self::normalizeRecipe($body);
            if ($recipe === null) {
                return Json::response($response, ['error' => 'invalid recipe'], 400);
            }

            $recipes = $campaign['recipes'] ?? [];
            if (isset($recipes[$recipe['recipe_id']])) {
                return Json::response($response, ['error' => 'recipe already exists'], 409);
            }

            $recipes[$recipe['recipe_id']] = $recipe;
            $campaign['recipes'] = $recipes;
            $campaigns->update($campaign);

            return Json::response($response, $recipe, 201);
        });

        $app->get('/v1/play/campaigns/{id}/recipes', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;
            $campaignId = $args['id'];

            $isMember = self::isOwningDm($actor, $campaign)
                || $campaigns->memberByUsername($campaignId, $actor['username']) !== null;
            if (!$isMember) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $recipes = $campaign['recipes'] ?? [];

            return Json::response($response, ['recipes' => array_values($recipes)], 200);
        });

        $app->post('/v1/play/campaigns/{id}/recipes/{recipe_id}/craft', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;
            $campaignId = $args['id'];

            $recipes = $campaign['recipes'] ?? [];
            $recipe = $recipes[$args['recipe_id']] ?? null;
            if ($recipe === null) {
                return Json::response($response, ['error' => 'recipe not found'], 404);
            }

            $body = Json::parseBody($request);
            $characterId = $body['character_id'] ?? null;
            if (!is_string($characterId) || $characterId === '') {
                return Json::response($response, ['error' => 'invalid character_id'], 400);
            }

            $member = $campaigns->memberByCharacterId($campaignId, $characterId);
            if ($member === null) {
                return Json::response($response, ['error' => 'character not found'], 404);
            }
            $member = self::withOwnerDefaults($member);
            $member = self::withInventoryDefaults($member);

            if ($actor['role'] !== 'player' || $member['owner'] !== $actor['username']) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $inventory = $member['inventory'];
            foreach ($recipe['ingredients'] as $ingredientId => $requiredQuantity) {
                if (($inventory[$ingredientId] ?? 0) < $requiredQuantity) {
                    return Json::response($response, ['error' => 'insufficient ingredients'], 409);
                }
            }

            foreach ($recipe['ingredients'] as $ingredientId => $requiredQuantity) {
                $remaining = $inventory[$ingredientId] - $requiredQuantity;
                if ($remaining > 0) {
                    $inventory[$ingredientId] = $remaining;
                } else {
                    unset($inventory[$ingredientId]);
                }
            }

            $outputItem = $recipe['output_item'];
            $inventory[$outputItem] = ($inventory[$outputItem] ?? 0) + $recipe['output_quantity'];

            $member['inventory'] = $inventory;
            $campaigns->updateMember($campaignId, $member['username'], $member);

            return Json::response($response, [
                'character_id' => $characterId,
                'recipe_id' => $recipe['recipe_id'],
                'output_item' => $outputItem,
                'output_quantity' => $recipe['output_quantity'],
            ], 201);
        });

        $app->post('/v1/play/campaigns/{id}/downtime/activities', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;

            if (!self::isOwningDm($actor, $campaign)) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $body = Json::parseBody($request);
            $activity = self::normalizeDowntimeActivity($body);
            if ($activity === null) {
                return Json::response($response, ['error' => 'invalid downtime activity'], 400);
            }

            $activities = $campaign['downtime_activities'] ?? [];
            if (isset($activities[$activity['activity_id']])) {
                return Json::response($response, ['error' => 'downtime activity already exists'], 409);
            }

            $activities[$activity['activity_id']] = $activity;
            $campaign['downtime_activities'] = $activities;
            $campaigns->update($campaign);

            return Json::response($response, $activity, 201);
        });

        $app->post('/v1/play/campaigns/{id}/characters/{character_id}/downtime/allocations', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;
            $campaignId = $args['id'];
            $characterId = $args['character_id'];

            $member = $campaigns->memberByCharacterId($campaignId, $characterId);
            if ($member === null) {
                return Json::response($response, ['error' => 'character not found'], 404);
            }
            $member = self::withOwnerDefaults($member);
            $member = self::withDowntimeDefaults($member);

            if ($actor['role'] !== 'player' || $member['owner'] !== $actor['username']) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $body = Json::parseBody($request);
            $activityId = $body['activity_id'] ?? null;
            if (!is_string($activityId) || $activityId === '') {
                return Json::response($response, ['error' => 'invalid activity_id'], 400);
            }

            $activities = $campaign['downtime_activities'] ?? [];
            if (!isset($activities[$activityId])) {
                return Json::response($response, ['error' => 'downtime activity not found'], 404);
            }

            $allocations = $member['downtime_allocations'];
            if (isset($allocations[$activityId])) {
                return Json::response($response, ['error' => 'downtime allocation already exists'], 409);
            }

            $allocations[$activityId] = ['cycles_completed' => 0, 'completions' => 0];
            $member['downtime_allocations'] = $allocations;
            $campaigns->updateMember($campaignId, $member['username'], $member);

            return Json::response($response, [
                'character_id' => $characterId,
                'activity_id' => $activityId,
                'cycles_completed' => 0,
                'completions' => 0,
            ], 201);
        });

        $app->post('/v1/play/campaigns/{id}/characters/{character_id}/downtime/allocations/{activity_id}/progress', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;
            $campaignId = $args['id'];
            $characterId = $args['character_id'];
            $activityId = $args['activity_id'];

            $member = $campaigns->memberByCharacterId($campaignId, $characterId);
            if ($member === null) {
                return Json::response($response, ['error' => 'character not found'], 404);
            }
            $member = self::withOwnerDefaults($member);
            $member = self::withDowntimeDefaults($member);

            if ($actor['role'] !== 'player' || $member['owner'] !== $actor['username']) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $activities = $campaign['downtime_activities'] ?? [];
            $activity = $activities[$activityId] ?? null;
            if ($activity === null) {
                return Json::response($response, ['error' => 'downtime activity not found'], 404);
            }

            $allocations = $member['downtime_allocations'];
            $allocation = $allocations[$activityId] ?? null;
            if ($allocation === null) {
                return Json::response($response, ['error' => 'downtime allocation not found'], 404);
            }

            $allocation['cycles_completed']++;
            if ($allocation['cycles_completed'] >= $activity['cycles_required']) {
                $allocation['cycles_completed'] = 0;
                $allocation['completions']++;
            }

            $allocations[$activityId] = $allocation;
            $member['downtime_allocations'] = $allocations;
            $campaigns->updateMember($campaignId, $member['username'], $member);

            return Json::response($response, [
                'character_id' => $characterId,
                'activity_id' => $activityId,
                'cycles_completed' => $allocation['cycles_completed'],
                'completions' => $allocation['completions'],
            ], 200);
        });

        $app->get('/v1/play/campaigns/{id}/characters/{character_id}/downtime/allocations/{activity_id}', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;
            $campaignId = $args['id'];
            $characterId = $args['character_id'];
            $activityId = $args['activity_id'];

            $isMember = self::isOwningDm($actor, $campaign)
                || $campaigns->memberByUsername($campaignId, $actor['username']) !== null;
            if (!$isMember) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $member = $campaigns->memberByCharacterId($campaignId, $characterId);
            if ($member === null) {
                return Json::response($response, ['error' => 'character not found'], 404);
            }
            $member = self::withDowntimeDefaults($member);

            $activities = $campaign['downtime_activities'] ?? [];
            if (!isset($activities[$activityId])) {
                return Json::response($response, ['error' => 'downtime activity not found'], 404);
            }

            $allocation = $member['downtime_allocations'][$activityId] ?? null;
            if ($allocation === null) {
                return Json::response($response, ['error' => 'downtime allocation not found'], 404);
            }

            return Json::response($response, [
                'character_id' => $characterId,
                'activity_id' => $activityId,
                'cycles_completed' => $allocation['cycles_completed'],
                'completions' => $allocation['completions'],
            ], 200);
        });

        $app->post('/v1/play/campaigns/{id}/content', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;
            $campaignId = $args['id'];

            if (!self::isOwningDm($actor, $campaign)) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $body = Json::parseBody($request);
            $contentId = $body['content_id'] ?? null;
            $kind = $body['kind'] ?? null;
            $text = $body['text'] ?? null;
            $tags = $body['tags'] ?? null;

            if (!is_string($contentId) || $contentId === '') {
                return Json::response($response, ['error' => 'invalid content_id'], 400);
            }
            if (!is_string($kind) || $kind === '') {
                return Json::response($response, ['error' => 'invalid kind'], 400);
            }
            if (!is_string($text) || $text === '') {
                return Json::response($response, ['error' => 'invalid text'], 400);
            }
            if (!self::isValidTagList($tags, false)) {
                return Json::response($response, ['error' => 'invalid tags'], 400);
            }

            $contentRecords = $campaign['content'] ?? [];
            foreach ($contentRecords as $record) {
                if ($record['content_id'] === $contentId) {
                    return Json::response($response, ['error' => 'content already exists'], 409);
                }
            }

            $content = [
                'content_id' => $contentId,
                'kind' => $kind,
                'text' => $text,
                'tags' => array_values($tags),
            ];

            $contentRecords[] = $content;
            $campaign['content'] = $contentRecords;
            $campaigns->update($campaign);

            return Json::response($response, $content, 201);
        });

        $app->put('/v1/play/campaigns/{id}/content/{content_id}/tags', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;
            $contentId = $args['content_id'];

            if (!self::isOwningDm($actor, $campaign)) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $contentRecords = $campaign['content'] ?? [];
            $index = null;
            foreach ($contentRecords as $i => $record) {
                if ($record['content_id'] === $contentId) {
                    $index = $i;
                    break;
                }
            }
            if ($index === null) {
                return Json::response($response, ['error' => 'content not found'], 404);
            }

            $body = Json::parseBody($request);
            $tags = $body['tags'] ?? null;
            if (!self::isValidTagList($tags, true)) {
                return Json::response($response, ['error' => 'invalid tags'], 400);
            }

            $contentRecords[$index]['tags'] = array_values($tags);
            $campaign['content'] = $contentRecords;
            $campaigns->update($campaign);

            return Json::response($response, $contentRecords[$index], 200);
        });

        $app->get('/v1/play/campaigns/{id}/content', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;
            $campaignId = $args['id'];

            $isDm = self::isOwningDm($actor, $campaign);
            $isMember = $isDm || $campaigns->memberByUsername($campaignId, $actor['username']) !== null;
            if (!$isMember) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $excludeTag = $request->getQueryParams()['exclude_tag'] ?? null;
            if ($excludeTag !== null && (!is_string($excludeTag) || $excludeTag === '')) {
                return Json::response($response, ['error' => 'invalid exclude_tag'], 400);
            }

            $contentRecords = $campaign['content'] ?? [];
            if (!$isDm && $excludeTag !== null) {
                $contentRecords = array_values(array_filter(
                    $contentRecords,
                    static fn (array $record) => !in_array($excludeTag, $record['tags'], true)
                ));
            }

            return Json::response($response, ['content' => $contentRecords], 200);
        });

        $app->post('/v1/play/campaigns/{id}/notes', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;
            $campaignId = $args['id'];

            $isDm = self::isOwningDm($actor, $campaign);
            $isMember = $isDm || $campaigns->memberByUsername($campaignId, $actor['username']) !== null;
            if (!$isMember) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $body = Json::parseBody($request);
            $noteId = $body['note_id'] ?? null;
            $text = $body['text'] ?? null;
            $visibility = $body['visibility'] ?? null;

            if (!is_string($noteId) || $noteId === '') {
                return Json::response($response, ['error' => 'invalid note_id'], 400);
            }
            if (!is_string($text) || $text === '') {
                return Json::response($response, ['error' => 'invalid text'], 400);
            }
            if ($visibility !== 'private' && $visibility !== 'party') {
                return Json::response($response, ['error' => 'invalid visibility'], 400);
            }

            $notes = $campaign['notes'] ?? [];
            if (isset($notes[$noteId])) {
                return Json::response($response, ['error' => 'note already exists'], 409);
            }

            $note = [
                'note_id' => $noteId,
                'text' => $text,
                'visibility' => $visibility,
                'owner' => $actor['username'],
            ];
            $notes[$noteId] = $note;
            $campaign['notes'] = $notes;
            $campaigns->update($campaign);

            return Json::response($response, $note, 201);
        });

        $app->get('/v1/play/campaigns/{id}/notes', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;
            $campaignId = $args['id'];

            $isDm = self::isOwningDm($actor, $campaign);
            $isMember = $isDm || $campaigns->memberByUsername($campaignId, $actor['username']) !== null;
            if (!$isMember) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $notes = array_values($campaign['notes'] ?? []);
            if (!$isDm) {
                $notes = array_values(array_filter(
                    $notes,
                    static fn (array $note) => $note['visibility'] === 'party' || $note['owner'] === $actor['username']
                ));
            }

            return Json::response($response, ['notes' => $notes], 200);
        });

        $app->get('/v1/play/campaigns/{id}/notes/{note_id}', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;
            $campaignId = $args['id'];

            $isDm = self::isOwningDm($actor, $campaign);
            $isMember = $isDm || $campaigns->memberByUsername($campaignId, $actor['username']) !== null;
            if (!$isMember) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $note = $campaign['notes'][$args['note_id']] ?? null;
            if ($note === null) {
                return Json::response($response, ['error' => 'note not found'], 404);
            }

            if (!$isDm && $note['visibility'] === 'private' && $note['owner'] !== $actor['username']) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            return Json::response($response, $note, 200);
        });

        $app->put('/v1/play/campaigns/{id}/notes/{note_id}', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;
            $campaignId = $args['id'];

            $isDm = self::isOwningDm($actor, $campaign);
            $isMember = $isDm || $campaigns->memberByUsername($campaignId, $actor['username']) !== null;
            if (!$isMember) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $noteId = $args['note_id'];
            $notes = $campaign['notes'] ?? [];
            $note = $notes[$noteId] ?? null;
            if ($note === null) {
                return Json::response($response, ['error' => 'note not found'], 404);
            }

            if ($note['owner'] !== $actor['username']) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $body = Json::parseBody($request);
            $text = $body['text'] ?? null;
            $visibility = $body['visibility'] ?? null;

            if (!is_string($text) || $text === '') {
                return Json::response($response, ['error' => 'invalid text'], 400);
            }
            if ($visibility !== 'private' && $visibility !== 'party') {
                return Json::response($response, ['error' => 'invalid visibility'], 400);
            }

            $note['text'] = $text;
            $note['visibility'] = $visibility;
            $notes[$noteId] = $note;
            $campaign['notes'] = $notes;
            $campaigns->update($campaign);

            return Json::response($response, $note, 200);
        });

        $app->post('/v1/play/campaigns/{id}/whispers', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;
            $campaignId = $args['id'];

            $sender = $campaigns->memberByUsername($campaignId, $actor['username']);
            if ($sender === null) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $body = Json::parseBody($request);
            $whisperId = $body['whisper_id'] ?? null;
            $toCharacterId = $body['to_character_id'] ?? null;
            $text = $body['text'] ?? null;

            if (!is_string($whisperId) || $whisperId === '') {
                return Json::response($response, ['error' => 'invalid whisper_id'], 400);
            }
            if (!is_string($toCharacterId) || $toCharacterId === '') {
                return Json::response($response, ['error' => 'invalid to_character_id'], 400);
            }
            if (!is_string($text) || $text === '') {
                return Json::response($response, ['error' => 'invalid text'], 400);
            }
            if (!$campaigns->characterIdExists($campaignId, $toCharacterId)) {
                return Json::response($response, ['error' => 'invalid to_character_id'], 400);
            }

            $whispers = $campaign['whispers'] ?? [];
            if (isset($whispers[$whisperId])) {
                return Json::response($response, ['error' => 'whisper already exists'], 409);
            }

            $whisper = [
                'whisper_id' => $whisperId,
                'from_character_id' => $sender['character_id'],
                'to_character_id' => $toCharacterId,
                'text' => $text,
            ];
            $whispers[$whisperId] = $whisper;
            $campaign['whispers'] = $whispers;
            $campaigns->update($campaign);

            return Json::response($response, $whisper, 201);
        });

        $app->get('/v1/play/campaigns/{id}/whispers', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;
            $campaignId = $args['id'];

            $isDm = self::isOwningDm($actor, $campaign);
            $member = $campaigns->memberByUsername($campaignId, $actor['username']);
            if (!$isDm && $member === null) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $whispers = array_values($campaign['whispers'] ?? []);
            if (!$isDm) {
                $characterId = $member['character_id'];
                $whispers = array_values(array_filter(
                    $whispers,
                    static fn (array $whisper) => $whisper['from_character_id'] === $characterId
                        || $whisper['to_character_id'] === $characterId
                ));
            }

            return Json::response($response, ['whispers' => $whispers], 200);
        });

        $app->get('/v1/play/campaigns/{id}/characters/{char_id}/sheet', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;
            $campaignId = $args['id'];

            $isDm = self::isOwningDm($actor, $campaign);
            $isMember = $isDm || $campaigns->memberByUsername($campaignId, $actor['username']) !== null;
            if (!$isMember) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $characterId = $args['char_id'];
            $member = $campaigns->memberByCharacterId($campaignId, $characterId);
            if ($member === null) {
                return Json::response($response, ['error' => 'character not found'], 404);
            }
            $member = self::withOwnerDefaults($member);

            if (!$isDm && $member['owner'] !== $actor['username']) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            return Json::response($response, [
                'character_id' => $characterId,
                'owner' => $member['owner'],
                'name' => $member['name'],
                'class' => $member['class'],
                'level' => 1,
                'proficiency_bonus' => 2,
                'hp_max' => 10,
                'armor_class' => 10,
            ], 200);
        });

        $app->post('/v1/play/campaigns/{id}/invitations', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;

            if (!self::isOwningDm($actor, $campaign)) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $body = Json::parseBody($request);
            $invitationId = $body['invitation_id'] ?? null;
            $username = $body['username'] ?? null;
            $characterId = $body['character_id'] ?? null;

            if (!is_string($invitationId) || $invitationId === '') {
                return Json::response($response, ['error' => 'invalid invitation_id'], 400);
            }
            if (!is_string($username) || $username === '') {
                return Json::response($response, ['error' => 'invalid username'], 400);
            }
            if (!is_string($characterId) || $characterId === '') {
                return Json::response($response, ['error' => 'invalid character_id'], 400);
            }

            $users = (new UserRepository(Database::connect($dbFile)))->all();
            $targetUser = $users[$username] ?? null;
            if ($targetUser === null || ($targetUser['role'] ?? null) !== 'player') {
                return Json::response($response, ['error' => 'invalid target user'], 400);
            }

            $invitations = $campaign['invitations'] ?? [];
            if (isset($invitations[$invitationId])) {
                return Json::response($response, ['error' => 'invitation already exists'], 409);
            }
            foreach ($invitations as $existing) {
                if ($existing['username'] === $username && $existing['status'] === 'pending') {
                    return Json::response($response, ['error' => 'invitation already pending'], 409);
                }
            }

            $invitation = [
                'invitation_id' => $invitationId,
                'username' => $username,
                'character_id' => $characterId,
                'status' => 'pending',
            ];
            $invitations[$invitationId] = $invitation;
            $campaign['invitations'] = $invitations;
            $campaigns->update($campaign);

            return Json::response($response, $invitation, 201);
        });

        $app->post('/v1/play/campaigns/{id}/invitations/{invitation_id}/accept', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;

            $invitationId = $args['invitation_id'];
            $invitations = $campaign['invitations'] ?? [];
            $invitation = $invitations[$invitationId] ?? null;
            if ($invitation === null) {
                return Json::response($response, ['error' => 'invitation not found'], 404);
            }

            if ($actor['username'] !== $invitation['username']) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }
            if ($invitation['status'] !== 'pending') {
                return Json::response($response, ['error' => 'invitation already accepted'], 409);
            }

            $invitation['status'] = 'accepted';
            $invitations[$invitationId] = $invitation;
            $campaign['invitations'] = $invitations;
            $campaigns->update($campaign);

            $member = [
                'username' => $invitation['username'],
                'character_id' => $invitation['character_id'],
                'name' => $invitation['username'],
                'class' => 'adventurer',
                'hp_current' => self::DEFAULT_HP_MAX,
                'hp_max' => self::DEFAULT_HP_MAX,
                'status' => 'alive',
                'death_save_successes' => 0,
                'death_save_failures' => 0,
                'owner' => $invitation['username'],
                'gold' => self::DEFAULT_GOLD,
            ];
            $campaigns->insertMember($campaign['id'], $invitation['username'], $invitation['character_id'], $member);

            return Json::response($response, $invitation, 200);
        });

        $app->get('/v1/play/campaigns/{id}/invitations', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [, $actor, $campaign] = $context;

            $invitations = array_values($campaign['invitations'] ?? []);
            if (!self::isOwningDm($actor, $campaign)) {
                $invitations = array_values(array_filter(
                    $invitations,
                    static fn (array $invitation) => $invitation['username'] === $actor['username']
                ));
            }

            return Json::response($response, ['invitations' => $invitations], 200);
        });

        $app->post('/v1/play/campaigns/{id}/delegations', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;

            if (!self::isOwningDm($actor, $campaign)) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $body = Json::parseBody($request);
            $username = $body['username'] ?? null;
            $powers = $body['powers'] ?? null;

            if (!is_string($username) || $username === '') {
                return Json::response($response, ['error' => 'invalid username'], 400);
            }
            if (!is_array($powers) || !array_is_list($powers) || count($powers) === 0) {
                return Json::response($response, ['error' => 'invalid powers'], 400);
            }
            if (count($powers) !== count(array_unique($powers))) {
                return Json::response($response, ['error' => 'duplicate powers'], 400);
            }
            foreach ($powers as $power) {
                if ($power !== 'narrate') {
                    return Json::response($response, ['error' => 'invalid powers'], 400);
                }
            }

            if ($campaigns->memberByUsername($campaign['id'], $username) === null) {
                return Json::response($response, ['error' => 'invalid target user'], 400);
            }

            $delegations = $campaign['delegations'] ?? [];
            $existing = $delegations[$username] ?? null;
            if ($existing !== null && $existing['active'] === true) {
                return Json::response($response, ['error' => 'delegation already active'], 409);
            }

            $delegation = [
                'username' => $username,
                'powers' => array_values($powers),
                'active' => true,
            ];
            $delegations[$username] = $delegation;
            $campaign['delegations'] = $delegations;

            $audit = $campaign['delegation_audit'] ?? [];
            $audit[] = [
                'username' => $username,
                'action' => 'granted',
                'powers' => array_values($powers),
            ];
            $campaign['delegation_audit'] = $audit;

            $campaigns->update($campaign);

            return Json::response($response, $delegation, 201);
        });

        $app->delete('/v1/play/campaigns/{id}/delegations/{username}', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;

            if (!self::isOwningDm($actor, $campaign)) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $username = $args['username'];
            $delegations = $campaign['delegations'] ?? [];
            $delegation = $delegations[$username] ?? null;
            if ($delegation === null) {
                return Json::response($response, ['error' => 'delegation not found'], 404);
            }

            $delegation['active'] = false;
            $delegations[$username] = $delegation;
            $campaign['delegations'] = $delegations;

            $audit = $campaign['delegation_audit'] ?? [];
            $audit[] = [
                'username' => $username,
                'action' => 'revoked',
                'powers' => $delegation['powers'],
            ];
            $campaign['delegation_audit'] = $audit;

            $campaigns->update($campaign);

            return Json::response($response, $delegation, 200);
        });

        $app->get('/v1/play/campaigns/{id}/delegations/audit', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [, $actor, $campaign] = $context;

            if (!self::isOwningDm($actor, $campaign)) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            return Json::response($response, ['entries' => array_values($campaign['delegation_audit'] ?? [])], 200);
        });

        $app->post('/v1/play/campaigns/{id}/audit-events', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;

            $isOwner = self::isOwningDm($actor, $campaign);
            $member = $campaigns->memberByUsername($campaign['id'], $actor['username']);
            if (!$isOwner && $member === null) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $body = Json::parseBody($request);
            $kind = $body['kind'] ?? null;
            $correlationId = $body['correlation_id'] ?? null;

            if (!is_string($kind) || $kind === '') {
                return Json::response($response, ['error' => 'invalid kind'], 400);
            }
            if (!is_string($correlationId) || $correlationId === '') {
                return Json::response($response, ['error' => 'invalid correlation_id'], 400);
            }

            $entries = $campaign['audit_events'] ?? [];
            foreach ($entries as $existingEntry) {
                if ($existingEntry['correlation_id'] === $correlationId) {
                    return Json::response($response, ['error' => 'duplicate correlation_id'], 409);
                }
            }

            $entry = [
                'kind' => $kind,
                'actor' => $actor['username'],
                'role' => $isOwner ? 'DM' : 'player',
                'timestamp' => count($entries) + 1,
                'correlation_id' => $correlationId,
            ];
            $entries[] = $entry;
            $campaign['audit_events'] = $entries;
            $campaigns->update($campaign);

            return Json::response($response, $entry, 201);
        });

        $app->get('/v1/play/campaigns/{id}/audit-events', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [, $actor, $campaign] = $context;

            if (!self::isOwningDm($actor, $campaign)) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            return Json::response($response, ['entries' => array_values($campaign['audit_events'] ?? [])], 200);
        });

        $app->post('/v1/play/campaigns/{id}/projection-events', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;
            $campaignId = $args['id'];

            $member = $campaigns->memberByUsername($campaignId, $actor['username']);
            if ($member === null) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            $body = Json::parseBody($request);
            $eventId = $body['event_id'] ?? null;
            $kind = $body['kind'] ?? null;

            if (!is_string($eventId) || $eventId === '') {
                return Json::response($response, ['error' => 'invalid event_id'], 400);
            }
            if ($kind !== 'set-story' && $kind !== 'increment-danger') {
                return Json::response($response, ['error' => 'invalid kind'], 400);
            }

            $value = $body['value'] ?? null;
            if ($kind === 'set-story') {
                if (!is_string($value) || $value === '') {
                    return Json::response($response, ['error' => 'invalid value'], 400);
                }
            } elseif (array_key_exists('value', $body) && $body['value'] !== null) {
                return Json::response($response, ['error' => 'invalid value'], 400);
            }

            $events = $campaign['projection_events'] ?? [];
            foreach ($events as $existing) {
                if ($existing['event_id'] === $eventId) {
                    return Json::response($response, ['error' => 'duplicate event_id'], 409);
                }
            }

            $stored = [
                'sequence' => count($events) + 1,
                'event_id' => $eventId,
                'kind' => $kind,
            ];
            if ($kind === 'set-story') {
                $stored['value'] = $value;
            }
            $events[] = $stored;
            $campaign['projection_events'] = $events;
            $campaigns->update($campaign);

            return Json::response($response, $stored, 201);
        });

        $app->get('/v1/play/campaigns/{id}/projection', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;
            $campaignId = $args['id'];

            $isOwner = self::isOwningDm($actor, $campaign);
            $member = $campaigns->memberByUsername($campaignId, $actor['username']);
            if (!$isOwner && $member === null) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            return Json::response($response, self::buildProjection($campaign['projection_events'] ?? []), 200);
        });

        $app->get('/v1/play/campaigns/{id}/projection/rebuild', function (Request $request, Response $response, array $args) use ($dbFile) {
            $context = self::context($request, $response, $args, $dbFile);
            if ($context instanceof Response) {
                return $context;
            }
            [$campaigns, $actor, $campaign] = $context;
            $campaignId = $args['id'];

            $isOwner = self::isOwningDm($actor, $campaign);
            $member = $campaigns->memberByUsername($campaignId, $actor['username']);
            if (!$isOwner && $member === null) {
                return Json::response($response, ['error' => 'forbidden'], 403);
            }

            return Json::response($response, self::buildProjection($campaign['projection_events'] ?? []), 200);
        });
    }

    /** Rebuilds the deterministic story/danger projection solely from ordered projection events. */
    private static function buildProjection(array $events): array
    {
        $story = '';
        $danger = 0;
        $appliedEventIds = [];

        foreach ($events as $event) {
            $appliedEventIds[] = $event['event_id'];
            if ($event['kind'] === 'set-story') {
                $story = $event['value'];
            } else {
                $danger++;
            }
        }

        return [
            'story' => $story,
            'danger' => $danger,
            'applied_event_ids' => $appliedEventIds,
        ];
    }

    /** Shared handler for the shop /buy and /sell endpoints. */
    private static function handleShopTrade(Request $request, Response $response, array $args, string $dbFile, string $mode): Response
    {
        $context = self::context($request, $response, $args, $dbFile);
        if ($context instanceof Response) {
            return $context;
        }
        [$campaigns, $actor, $campaign] = $context;
        $campaignId = $args['id'];

        $settlementId = $args['settlement_id'];
        $settlements = $campaign['settlements'] ?? [];
        $settlement = $settlements[$settlementId] ?? null;
        if ($settlement === null) {
            return Json::response($response, ['error' => 'settlement not found'], 404);
        }

        $shopId = $args['shop_id'];
        $shops = $settlement['shops'] ?? [];
        $shop = $shops[$shopId] ?? null;
        if ($shop === null) {
            return Json::response($response, ['error' => 'shop not found'], 404);
        }

        if ($actor['role'] !== 'player') {
            return Json::response($response, ['error' => 'forbidden'], 403);
        }

        $body = Json::parseBody($request);
        $characterId = $body['character_id'] ?? null;
        $itemId = $body['item_id'] ?? null;
        $quantity = $body['quantity'] ?? null;

        if (!is_string($characterId) || $characterId === '') {
            return Json::response($response, ['error' => 'invalid character_id'], 400);
        }

        $member = $campaigns->memberByCharacterId($campaignId, $characterId);
        if ($member === null) {
            return Json::response($response, ['error' => 'character not found'], 404);
        }
        $member = self::withOwnerDefaults($member);
        $member = self::withGoldDefaults($member);
        $member = self::withInventoryDefaults($member);

        if ($member['owner'] !== $actor['username']) {
            return Json::response($response, ['error' => 'forbidden'], 403);
        }

        if (!in_array($itemId, self::INVENTORY_ITEM_IDS, true)) {
            return Json::response($response, ['error' => 'invalid item_id'], 400);
        }
        if (!is_int($quantity) || $quantity < 1) {
            return Json::response($response, ['error' => 'invalid quantity'], 400);
        }

        $stock = $shop['stock'];
        $inventory = $member['inventory'];
        $gold = $member['gold'];

        if ($mode === 'buy') {
            $held = $stock[$itemId] ?? 0;
            $cost = $shop['buy_price'] * $quantity;
            if ($quantity > $held || $gold < $cost) {
                return Json::response($response, ['error' => 'insufficient stock or funds'], 409);
            }

            $stock[$itemId] = $held - $quantity;
            $gold -= $cost;
            $inventory[$itemId] = ($inventory[$itemId] ?? 0) + $quantity;
        } else {
            $held = $inventory[$itemId] ?? 0;
            if ($quantity > $held) {
                return Json::response($response, ['error' => 'insufficient inventory'], 409);
            }

            $remaining = $held - $quantity;
            if ($remaining > 0) {
                $inventory[$itemId] = $remaining;
            } else {
                unset($inventory[$itemId]);
            }
            $gold += $shop['sell_price'] * $quantity;
            $stock[$itemId] = ($stock[$itemId] ?? 0) + $quantity;
        }

        $shop['stock'] = $stock;
        $shops[$shopId] = $shop;
        $settlement['shops'] = $shops;
        $settlements[$settlementId] = $settlement;
        $campaign['settlements'] = $settlements;
        $campaigns->update($campaign);

        $member['inventory'] = $inventory;
        $member['gold'] = $gold;
        $campaigns->updateMember($campaignId, $member['username'], $member);

        return Json::response($response, [
            'character_id' => $characterId,
            'item_id' => $itemId,
            'quantity' => $quantity,
            'gold' => $gold,
            'stock' => $stock[$itemId] ?? 0,
        ], 200);
    }

    /** Validates and normalizes a recipe create payload, returning null when invalid. */
    private static function normalizeRecipe(mixed $body): ?array
    {
        if (!is_array($body)) {
            return null;
        }

        $recipeId = $body['recipe_id'] ?? null;
        $name = $body['name'] ?? null;
        $ingredients = $body['ingredients'] ?? null;
        $outputItem = $body['output_item'] ?? null;
        $outputQuantity = $body['output_quantity'] ?? null;

        if (!is_string($recipeId) || $recipeId === '') {
            return null;
        }
        if (!is_string($name) || $name === '') {
            return null;
        }
        if (!is_array($ingredients) || array_is_list($ingredients) || count($ingredients) === 0) {
            return null;
        }

        $normalizedIngredients = [];
        foreach ($ingredients as $itemId => $qty) {
            if (!in_array($itemId, self::INVENTORY_ITEM_IDS, true)) {
                return null;
            }
            if (!is_int($qty) || $qty < 1) {
                return null;
            }
            $normalizedIngredients[$itemId] = $qty;
        }

        if (!in_array($outputItem, self::INVENTORY_ITEM_IDS, true)) {
            return null;
        }
        if (!is_int($outputQuantity) || $outputQuantity < 1) {
            return null;
        }

        return [
            'recipe_id' => $recipeId,
            'name' => $name,
            'ingredients' => $normalizedIngredients,
            'output_item' => $outputItem,
            'output_quantity' => $outputQuantity,
        ];
    }

    /** Validates and normalizes a downtime activity create payload, returning null when invalid. */
    private static function normalizeDowntimeActivity(mixed $body): ?array
    {
        if (!is_array($body)) {
            return null;
        }

        $activityId = $body['activity_id'] ?? null;
        $name = $body['name'] ?? null;
        $cyclesRequired = $body['cycles_required'] ?? null;

        if (!is_string($activityId) || $activityId === '') {
            return null;
        }
        if (!is_string($name) || $name === '') {
            return null;
        }
        if (!is_int($cyclesRequired) || $cyclesRequired < 1 || $cyclesRequired > 10) {
            return null;
        }

        return [
            'activity_id' => $activityId,
            'name' => $name,
            'cycles_required' => $cyclesRequired,
        ];
    }

    /** Validates and normalizes a shop create payload, returning null when invalid. */
    private static function normalizeShop(mixed $body): ?array
    {
        if (!is_array($body)) {
            return null;
        }

        $shopId = $body['shop_id'] ?? null;
        $name = $body['name'] ?? null;
        $stock = $body['stock'] ?? null;
        $buyPrice = $body['buy_price'] ?? null;
        $sellPrice = $body['sell_price'] ?? null;

        if (!is_string($shopId) || $shopId === '') {
            return null;
        }
        if (!is_string($name) || $name === '') {
            return null;
        }
        if (!is_array($stock) || array_is_list($stock) || count($stock) === 0) {
            return null;
        }

        $normalizedStock = [];
        foreach ($stock as $itemId => $qty) {
            if (!in_array($itemId, self::INVENTORY_ITEM_IDS, true)) {
                return null;
            }
            if (!is_int($qty) || $qty < 1) {
                return null;
            }
            $normalizedStock[$itemId] = $qty;
        }

        if (!is_int($buyPrice) || $buyPrice < 1) {
            return null;
        }
        if (!is_int($sellPrice) || $sellPrice < 0) {
            return null;
        }

        return [
            'shop_id' => $shopId,
            'name' => $name,
            'stock' => $normalizedStock,
            'buy_price' => $buyPrice,
            'sell_price' => $sellPrice,
        ];
    }

    private const SEASON_OFFSETS = ['spring' => 0, 'summer' => 1, 'autumn' => 2, 'winter' => 3];

    private const WEATHER_BY_INDEX = [0 => 'clear', 1 => 'rain', 2 => 'wind', 3 => 'snow'];

    /** Builds the exact calendar response, deriving deterministic weather from day + season. */
    private static function calendarView(array $calendar): array
    {
        $offset = self::SEASON_OFFSETS[$calendar['season']];
        $weather = self::WEATHER_BY_INDEX[($calendar['day'] + $offset) % 4];

        return [
            'day' => $calendar['day'],
            'season' => $calendar['season'],
            'weather' => $weather,
        ];
    }

    private const INVENTORY_ITEM_IDS = ['healing-potion', 'torch', 'leather-armor', 'ring-of-protection', 'amulet-of-health'];

    private const EQUIPMENT_SLOTS = ['armor' => ['leather-armor'], 'accessory' => ['ring-of-protection', 'amulet-of-health']];

    private const ITEM_SLOT_MAP = [
        'leather-armor' => 'armor',
        'ring-of-protection' => 'accessory',
        'amulet-of-health' => 'accessory',
    ];

    private const ATTUNABLE_ITEM_IDS = ['ring-of-protection', 'amulet-of-health'];

    private const MAX_ATTUNEMENTS = 1;

    private const CONSUMABLE_ITEM_IDS = ['healing-potion'];

    private const CONSUMABLE_EFFECTS = [
        'healing-potion' => ['type' => 'healing', 'hp_restored' => 5],
    ];

    /** Fills in death-save/status fields for members created before this stage existed. */
    private static function withDeathSaveDefaults(array $member): array
    {
        $member['status'] ??= 'alive';
        $member['death_save_successes'] ??= 0;
        $member['death_save_failures'] ??= 0;

        return $member;
    }

    /** Fills in the owner field for members created before this stage existed; characters begin unowned. */
    private static function withOwnerDefaults(array $member): array
    {
        $member['owner'] ??= null;

        return $member;
    }

    /** Fills in the spell cast history for members created before this stage existed. */
    private static function withCastDefaults(array $member): array
    {
        $member['casts'] ??= [];

        return $member;
    }

    /** Fills in the concentration state for members created before this stage existed. */
    private static function withConcentrationDefaults(array $member): array
    {
        $member['concentration'] ??= null;

        return $member;
    }

    /** Fills in the inventory item-stack map (item_id => quantity) for members created before this stage existed. */
    private static function withInventoryDefaults(array $member): array
    {
        $member['inventory'] ??= [];

        return $member;
    }

    /** Fills in the equipment slot map for members created before this stage existed. */
    private static function withEquipmentDefaults(array $member): array
    {
        $member['equipment'] ??= [];

        return $member;
    }

    /** Fills in the gold balance for members created before this stage existed. */
    private static function withGoldDefaults(array $member): array
    {
        $member['gold'] ??= self::DEFAULT_GOLD;

        return $member;
    }

    /** Fills in the cumulative quest-reward ledger for members created before this stage existed. */
    private static function withQuestRewardDefaults(array $member): array
    {
        $member['quest_rewards'] ??= ['xp' => 0, 'items' => []];

        return $member;
    }

    /** Fills in the downtime allocation map (activity_id => {cycles_completed, completions}) for members created before this stage existed. */
    private static function withDowntimeDefaults(array $member): array
    {
        $member['downtime_allocations'] ??= [];

        return $member;
    }

    /** Shared handler for /damage and /heal: applies a deterministic HP delta to a monster or party-member combatant. */
    private static function applyHpChange(Request $request, Response $response, array $args, string $dbFile, string $mode): Response
    {
        $context = self::context($request, $response, $args, $dbFile);
        if ($context instanceof Response) {
            return $context;
        }
        [$campaigns, $actor, $campaign] = $context;
        $campaignId = $args['id'];

        if (!self::isOwningDm($actor, $campaign)) {
            return Json::response($response, ['error' => 'forbidden'], 403);
        }

        $encounterId = $args['enc_id'];
        $encounters = $campaign['encounters'] ?? [];
        if (!isset($encounters[$encounterId])) {
            return Json::response($response, ['error' => 'encounter not found'], 404);
        }

        $body = Json::parseBody($request);
        $target = $body['target'] ?? null;
        $amount = $body['amount'] ?? null;

        if (!is_string($target) || $target === '') {
            return Json::response($response, ['error' => 'invalid target'], 400);
        }
        if (!is_int($amount) || $amount < 0) {
            return Json::response($response, ['error' => 'invalid amount'], 400);
        }

        $encounter = $encounters[$encounterId];
        $monsters = $encounter['monsters'] ?? [];

        if (isset($monsters[$target])) {
            $monster = $monsters[$target];
            $hpBefore = $monster['hp_current'];
            $hpMax = $monster['hp_max'];
            $hpAfter = $mode === 'damage'
                ? max(0, $hpBefore - $amount)
                : min($hpMax, $hpBefore + $amount);

            $monster['hp_current'] = $hpAfter;
            $monsters[$target] = $monster;
            $encounter['monsters'] = $monsters;
            $encounters[$encounterId] = $encounter;
            $campaign['encounters'] = $encounters;
            $campaigns->update($campaign);
        } else {
            $combatants = $encounter['combatants'] ?? [];
            if (!isset($combatants[$target])) {
                return Json::response($response, ['error' => 'target not found'], 404);
            }

            $member = $campaigns->memberByUsername($campaignId, $target);
            if ($member === null) {
                return Json::response($response, ['error' => 'target not found'], 404);
            }

            $hpBefore = $member['hp_current'];
            $hpMax = $member['hp_max'];
            $hpAfter = $mode === 'damage'
                ? max(0, $hpBefore - $amount)
                : min($hpMax, $hpBefore + $amount);

            $member['hp_current'] = $hpAfter;
            $campaigns->updateMember($campaignId, $target, $member);
        }

        $result = [
            'target' => $target,
            'hp_before' => $hpBefore,
            'hp_after' => $hpAfter,
        ];
        $result[$mode === 'damage' ? 'damage' : 'healing'] = $amount;

        return Json::response($response, $result, 200);
    }

    /** Fetches the encounter from a loaded campaign, or a ready-to-return 404 Response. */
    private static function requireEncounter(array $campaign, Response $response, string $encounterId): array|Response
    {
        $encounters = $campaign['encounters'] ?? [];

        return $encounters[$encounterId] ?? Json::response($response, ['error' => 'encounter not found'], 404);
    }

    private static function requireLoot(array $campaign, Response $response, string $lootId): array|Response
    {
        $loot = $campaign['loot'] ?? [];

        return $loot[$lootId] ?? Json::response($response, ['error' => 'loot not found'], 404);
    }

    private static function requireNpc(array $campaign, Response $response, string $npcId): array|Response
    {
        $npcs = $campaign['npcs'] ?? [];

        return $npcs[$npcId] ?? Json::response($response, ['error' => 'npc not found'], 404);
    }

    private static function requireFaction(array $campaign, Response $response, string $factionId): array|Response
    {
        $factions = $campaign['factions'] ?? [];

        return $factions[$factionId] ?? Json::response($response, ['error' => 'faction not found'], 404);
    }

    /** True when the id names a campaign member's character or an NPC in this campaign. */
    private static function campaignEntityExists(PlayCampaignRepository $campaigns, array $campaign, string $campaignId, string $entityId): bool
    {
        if (isset($campaign['npcs'][$entityId])) {
            return true;
        }

        return $campaigns->characterIdExists($campaignId, $entityId);
    }

    /**
     * Deterministic initiative order combining bound party combatants and monsters.
     * Ties break by name ascending, matching the standalone combat-session ordering.
     */
    private static function combatTurnOrder(array $encounter): array
    {
        $entries = [];
        foreach ($encounter['monsters'] ?? [] as $monster) {
            $entries[] = [
                'key' => $monster['monster_id'],
                'name' => $monster['name'],
                'kind' => 'monster',
                'initiative' => $monster['initiative'],
            ];
        }
        foreach ($encounter['combatants'] ?? [] as $combatant) {
            $entries[] = [
                'key' => $combatant['member'],
                'name' => $combatant['name'],
                'kind' => 'player',
                'initiative' => $combatant['initiative'],
            ];
        }

        usort($entries, function ($a, $b) {
            if ($a['initiative'] !== $b['initiative']) {
                return $b['initiative'] <=> $a['initiative'];
            }
            return $a['name'] <=> $b['name'];
        });

        $override = $encounter['turn_order'] ?? null;
        if (is_array($override) && !empty($override)) {
            $byKey = [];
            foreach ($entries as $entry) {
                $byKey[$entry['key']] = $entry;
            }

            $reordered = [];
            foreach ($override as $key) {
                if (isset($byKey[$key])) {
                    $reordered[] = $byKey[$key];
                    unset($byKey[$key]);
                }
            }
            foreach ($byKey as $entry) {
                $reordered[] = $entry;
            }

            return $reordered;
        }

        return $entries;
    }

    /** Decrements remaining_rounds for the given target's conditions, dropping any that expire. */
    private static function decrementConditions(array $conditions, string $target): array
    {
        if (!isset($conditions[$target])) {
            return $conditions;
        }

        $remaining = [];
        foreach ($conditions[$target] as $condition) {
            $condition['remaining_rounds']--;
            if ($condition['remaining_rounds'] > 0) {
                $remaining[] = $condition;
            }
        }

        if (empty($remaining)) {
            unset($conditions[$target]);
        } else {
            $conditions[$target] = $remaining;
        }

        return $conditions;
    }

    /**
     * Resolves the repository, actor, and campaign together — the auth+lookup
     * sequence shared by nearly every /v1/play/campaigns/{id}/* handler. Returns
     * [$campaigns, $actor, $campaign] on success, or a ready-to-return Response
     * (401 for a missing/invalid actor, 404 for an unknown campaign).
     */
    private static function context(Request $request, Response $response, array $args, string $dbFile): array|Response
    {
        $campaigns = self::repo($dbFile);

        $actor = self::requireActor($request, $response);
        if ($actor instanceof Response) {
            return $actor;
        }

        $campaign = self::requireCampaign($campaigns, $response, $args['id']);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        return [$campaigns, $actor, $campaign];
    }

    private static function repo(string $dbFile): PlayCampaignRepository
    {
        return new PlayCampaignRepository(Database::connect($dbFile));
    }

    /** Resolves the bearer actor, or a ready-to-return 401 Response if the header is missing/invalid. */
    private static function requireActor(Request $request, Response $response): array|Response
    {
        $actor = Auth::actor($request);

        return $actor ?? Json::response($response, ['error' => 'unauthorized'], 401);
    }

    /** Fetches the play campaign, or a ready-to-return 404 Response if it doesn't exist. */
    private static function requireCampaign(PlayCampaignRepository $campaigns, Response $response, string $campaignId): array|Response
    {
        $campaign = $campaigns->fetch($campaignId);

        return $campaign ?? Json::response($response, ['error' => 'campaign not found'], 404);
    }

    /** True when the actor is the DM who owns this campaign. */
    private static function isOwningDm(array $actor, array $campaign): bool
    {
        return $actor['role'] === 'dm' && $campaign['owner'] === $actor['username'];
    }

    /** True when the given username holds an active delegation with the given power in this campaign. */
    private static function hasActiveDelegatePower(array $campaign, string $username, string $power): bool
    {
        $delegation = $campaign['delegations'][$username] ?? null;

        return $delegation !== null
            && $delegation['active'] === true
            && in_array($power, $delegation['powers'], true);
    }

    /** Validates a tag list: a list of unique nonempty strings. Empty lists are only allowed when $allowEmpty is true. */
    private static function isValidTagList(mixed $tags, bool $allowEmpty): bool
    {
        if (!is_array($tags) || !array_is_list($tags)) {
            return false;
        }
        if (count($tags) === 0) {
            return $allowEmpty;
        }
        foreach ($tags as $tag) {
            if (!is_string($tag) || $tag === '') {
                return false;
            }
        }

        return count($tags) === count(array_unique($tags));
    }

    /** Trims and validates settlement services, returning null when invalid. */
    private static function normalizeServices(mixed $services): ?array
    {
        if (!is_array($services) || !array_is_list($services) || count($services) === 0) {
            return null;
        }

        $normalized = [];
        foreach ($services as $service) {
            if (!is_string($service)) {
                return null;
            }
            $trimmed = trim($service);
            if ($trimmed === '') {
                return null;
            }
            $normalized[] = $trimmed;
        }

        if (count($normalized) !== count(array_unique($normalized))) {
            return null;
        }

        return $normalized;
    }

    /** Builds the player-facing settlement view, limiting discovered_by to the player's own character. */
    private static function playerSettlementView(array $settlement, string $characterId): array
    {
        $settlement['discovered_by'] = in_array($characterId, $settlement['discovered_by'], true)
            ? [$characterId]
            : [];

        return $settlement;
    }
}
