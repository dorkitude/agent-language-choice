<?php

namespace App\Play;

use App\Auth\SessionAuth;
use App\Storage\KvStore;
use App\Support\Json;
use App\Support\Validators;
use Symfony\Component\HttpFoundation\JsonResponse;
use Symfony\Component\HttpFoundation\Request;

/**
 * Handlers for the protected campaign-play surface (/v1/play/*).
 *
 * All campaign state here lives in a single KV blob (see KvStore) keyed by
 * campaign id, distinct from the persisted /v1/campaigns/* tables owned by
 * CampaignController. Every handler follows the same shape: authenticate,
 * validate the body, then read-modify-write the campaign inside
 * withCampaigns() so concurrent requests observe a consistent state.
 */
final class PlayController
{
    private const STORE_KEY = 'play_campaigns';

    /** Default max hit points assigned to a party member on joining. */
    private const DEFAULT_HP_MAX = 20;

    public function createCampaign(Request $request, array $body): JsonResponse
    {
        $actor = $this->requireActor($request);
        if ($actor instanceof JsonResponse) {
            return $actor;
        }
        if ($actor['role'] !== 'dm') {
            return Json::error('forbidden', 403);
        }

        $id = $body['id'] ?? null;
        $name = $body['name'] ?? null;
        $maxPlayers = $body['max_players'] ?? null;

        if (!Validators::isValidId($id) || !is_string($name) || $name === ''
            || !Validators::isValidInt($maxPlayers) || (int) $maxPlayers <= 0) {
            return Json::error('invalid request');
        }
        $maxPlayers = (int) $maxPlayers;

        return $this->withCampaigns(static function (array &$state) use ($id, $name, $actor, $maxPlayers) {
            if (isset($state['campaigns'][$id])) {
                return Json::error('campaign already exists', 409);
            }

            $campaign = [
                'id' => $id,
                'name' => $name,
                'owner' => $actor['username'],
                'status' => 'lobby',
                'max_players' => $maxPlayers,
            ];
            $state['campaigns'][$id] = $campaign;

            return new JsonResponse($campaign, 201);
        });
    }

    public function joinCampaign(Request $request, array $body, string $campaignId): JsonResponse
    {
        $actor = $this->requireActor($request);
        if ($actor instanceof JsonResponse) {
            return $actor;
        }
        if ($actor['role'] !== 'player') {
            return Json::error('forbidden', 403);
        }

        $characterId = $body['character_id'] ?? null;
        $name = $body['name'] ?? null;
        $class = $body['class'] ?? null;

        if (!Validators::isValidId($characterId) || !is_string($name) || $name === ''
            || !is_string($class) || $class === '') {
            return Json::error('invalid request');
        }

        return $this->withCampaigns(function (array &$state) use ($campaignId, $actor, $characterId, $name, $class) {
            $campaign = self::findCampaign($state, $campaignId);
            if ($campaign === null) {
                return Json::error('campaign not found', 404);
            }

            $members = $campaign['members'] ?? [];

            foreach ($members as $member) {
                if ($member['username'] === $actor['username'] || $member['character_id'] === $characterId) {
                    return Json::error('conflict', 409);
                }
            }

            if (count($members) >= $campaign['max_players']) {
                return Json::error('party is full', 409);
            }

            $member = [
                'username' => $actor['username'],
                'character_id' => $characterId,
                'name' => $name,
                'class' => $class,
                'hp_current' => self::DEFAULT_HP_MAX,
                'hp_max' => self::DEFAULT_HP_MAX,
            ];
            $members[] = $member;
            $campaign['members'] = $members;
            $state['campaigns'][$campaignId] = $campaign;

            return new JsonResponse($member, 201);
        });
    }

    public function startCampaign(Request $request, string $campaignId): JsonResponse
    {
        $actor = $this->requireActor($request);
        if ($actor instanceof JsonResponse) {
            return $actor;
        }

        return $this->withCampaigns(function (array &$state) use ($campaignId, $actor) {
            $campaign = self::findCampaign($state, $campaignId);
            if ($campaign === null) {
                return Json::error('campaign not found', 404);
            }

            if (!self::isOwner($campaign, $actor['username'])) {
                return Json::error('forbidden', 403);
            }

            $members = $campaign['members'] ?? [];

            if ($campaign['status'] !== 'lobby' || count($members) < 2) {
                return Json::error('conflict', 409);
            }

            $campaign['status'] = 'active';
            $campaign['current_actor'] = $members[0]['username'];
            $campaign['phase'] = 'player';
            $campaign['turn_number'] = 1;
            $state['campaigns'][$campaignId] = $campaign;

            return new JsonResponse([
                'id' => $campaign['id'],
                'status' => $campaign['status'],
                'current_actor' => $campaign['current_actor'],
                'turn_number' => $campaign['turn_number'],
            ]);
        });
    }

    public function addNarration(Request $request, array $body, string $campaignId): JsonResponse
    {
        $actor = $this->requireActor($request);
        if ($actor instanceof JsonResponse) {
            return $actor;
        }
        if ($actor['role'] !== 'dm') {
            return Json::error('forbidden', 403);
        }

        $text = $body['text'] ?? null;
        if (!is_string($text) || $text === '') {
            return Json::error('invalid request');
        }

        return $this->withCampaigns(function (array &$state) use ($campaignId, $text) {
            $campaign = self::findCampaign($state, $campaignId);
            if ($campaign === null) {
                return Json::error('campaign not found', 404);
            }

            $events = $campaign['events'] ?? [];
            $event = [
                'sequence' => count($events) + 1,
                'kind' => 'narration',
                'actor' => 'dm',
                'text' => $text,
            ];
            $events[] = $event;
            $campaign['events'] = $events;
            $state['campaigns'][$campaignId] = $campaign;

            return new JsonResponse($event, 201);
        });
    }

    public function submitAction(Request $request, array $body, string $campaignId): JsonResponse
    {
        $actor = $this->requireActor($request);
        if ($actor instanceof JsonResponse) {
            return $actor;
        }

        $type = $body['type'] ?? null;
        $text = $body['text'] ?? null;

        if (!is_string($type) || $type === '' || !is_string($text) || $text === '') {
            return Json::error('invalid request');
        }

        return $this->withCampaigns(function (array &$state) use ($campaignId, $actor, $type, $text) {
            $campaign = self::findCampaign($state, $campaignId);
            if ($campaign === null) {
                return Json::error('campaign not found', 404);
            }

            if (!self::isParticipant($campaign, $actor['username'])) {
                return Json::error('forbidden', 403);
            }

            if ($actor['role'] !== 'player' || $actor['username'] !== ($campaign['current_actor'] ?? null)) {
                return Json::error('conflict', 409);
            }

            $events = $campaign['events'] ?? [];
            $event = [
                'sequence' => count($events) + 1,
                'kind' => 'action',
                'actor' => $actor['username'],
                'type' => $type,
                'text' => $text,
                'next_actor' => 'dm',
            ];
            $events[] = $event;
            $campaign['events'] = $events;
            $campaign['current_actor'] = $campaign['owner'];
            $campaign['phase'] = 'dm';
            $state['campaigns'][$campaignId] = $campaign;

            return new JsonResponse($event, 201);
        });
    }

    public function getTurn(Request $request, string $campaignId): JsonResponse
    {
        $actor = $this->requireActor($request);
        if ($actor instanceof JsonResponse) {
            return $actor;
        }

        return $this->withCampaigns(function (array &$state) use ($campaignId, $actor) {
            $campaign = self::findCampaign($state, $campaignId);
            if ($campaign === null) {
                return Json::error('campaign not found', 404);
            }

            if (!self::isParticipant($campaign, $actor['username'])) {
                return Json::error('forbidden', 403);
            }

            $queue = [];
            foreach ($campaign['members'] ?? [] as $member) {
                $queue[] = $member['username'];
                $queue[] = 'dm';
            }

            $turnNumber = $campaign['turn_number'] ?? null;

            return new JsonResponse([
                'campaign_id' => $campaign['id'],
                'current_actor' => $campaign['current_actor'] ?? null,
                'phase' => $campaign['phase'] ?? $campaign['status'],
                'turn_number' => $turnNumber,
                'queue' => $queue,
                'overdue' => false,
                'logical_deadline' => ($turnNumber ?? 1) + 1,
            ]);
        });
    }

    public function nudgeTurn(Request $request, array $body, string $campaignId): JsonResponse
    {
        $actor = $this->requireActor($request);
        if ($actor instanceof JsonResponse) {
            return $actor;
        }

        $message = $body['message'] ?? null;
        if (!is_string($message) || $message === '') {
            return Json::error('invalid request');
        }

        return $this->withCampaigns(function (array &$state) use ($campaignId, $actor, $message) {
            $campaign = self::findCampaign($state, $campaignId);
            if ($campaign === null) {
                return Json::error('campaign not found', 404);
            }

            if (!self::isOwner($campaign, $actor['username'])) {
                return Json::error('forbidden', 403);
            }

            $nudgeCount = ($campaign['nudge_count'] ?? 0) + 1;
            $campaign['nudge_count'] = $nudgeCount;

            $events = $campaign['events'] ?? [];
            $events[] = [
                'sequence' => count($events) + 1,
                'kind' => 'nudge',
                'actor' => $actor['username'],
                'text' => $message,
            ];
            $campaign['events'] = $events;

            $state['campaigns'][$campaignId] = $campaign;

            return new JsonResponse([
                'campaign_id' => $campaign['id'],
                'actor' => $actor['username'],
                'target' => $campaign['current_actor'] ?? null,
                'message' => $message,
                'nudge_count' => $nudgeCount,
            ], 201);
        });
    }

    public function myTurn(Request $request, string $campaignId): JsonResponse
    {
        $actor = $this->requireActor($request);
        if ($actor instanceof JsonResponse) {
            return $actor;
        }

        return $this->withCampaigns(function (array &$state) use ($campaignId, $actor) {
            $campaign = self::findCampaign($state, $campaignId);
            if ($campaign === null) {
                return Json::error('campaign not found', 404);
            }

            $isOwner = self::isOwner($campaign, $actor['username']);
            $member = self::findMember($campaign, $actor['username']);

            if ((!$isOwner && $member === null) || $actor['role'] !== 'player' || $member === null) {
                return Json::error('forbidden', 403);
            }

            return new JsonResponse([
                'is_my_turn' => ($campaign['current_actor'] ?? null) === $actor['username'],
                'current_actor' => $campaign['current_actor'] ?? null,
                'character' => [
                    'id' => $member['character_id'],
                    'name' => $member['name'],
                ],
                'recent_events' => $campaign['events'] ?? [],
            ]);
        });
    }

    public function addResolution(Request $request, array $body, string $campaignId): JsonResponse
    {
        $actor = $this->requireActor($request);
        if ($actor instanceof JsonResponse) {
            return $actor;
        }

        $text = $body['text'] ?? null;
        if (!is_string($text) || $text === '') {
            return Json::error('invalid request');
        }

        return $this->withCampaigns(function (array &$state) use ($campaignId, $actor, $text) {
            $campaign = self::findCampaign($state, $campaignId);
            if ($campaign === null) {
                return Json::error('campaign not found', 404);
            }

            $isOwner = self::isOwner($campaign, $actor['username']);
            if (!$isOwner && !self::isMember($campaign, $actor['username'])) {
                return Json::error('forbidden', 403);
            }

            if (!$isOwner || ($campaign['current_actor'] ?? null) !== $campaign['owner']) {
                return Json::error('conflict', 409);
            }

            $members = $campaign['members'] ?? [];
            $events = $campaign['events'] ?? [];
            $nextActor = self::nextTurnActor($members, $events);

            $event = [
                'sequence' => count($events) + 1,
                'kind' => 'resolution',
                'actor' => $actor['username'],
                'text' => $text,
                'next_actor' => $nextActor,
            ];
            $events[] = $event;
            $campaign['events'] = $events;
            $campaign['current_actor'] = $nextActor;
            $campaign['phase'] = 'player';
            $campaign['turn_number'] = ($campaign['turn_number'] ?? 1) + 1;
            $state['campaigns'][$campaignId] = $campaign;

            return new JsonResponse([
                'sequence' => $event['sequence'],
                'kind' => $event['kind'],
                'actor' => $event['actor'],
                'text' => $event['text'],
                'next_actor' => $nextActor,
                'turn_number' => $campaign['turn_number'],
            ], 201);
        });
    }

    public function updateDocument(Request $request, array $body, string $campaignId): JsonResponse
    {
        $actor = $this->requireActor($request);
        if ($actor instanceof JsonResponse) {
            return $actor;
        }

        $story = $body['story'] ?? null;
        $dmNotes = $body['dm_notes'] ?? null;

        if (!is_string($story) || $story === '' || !is_string($dmNotes) || $dmNotes === '') {
            return Json::error('invalid request');
        }

        return $this->withCampaigns(function (array &$state) use ($campaignId, $actor, $story, $dmNotes) {
            $campaign = self::findCampaign($state, $campaignId);
            if ($campaign === null) {
                return Json::error('campaign not found', 404);
            }

            if (!self::isOwner($campaign, $actor['username'])) {
                return Json::error('forbidden', 403);
            }

            $campaign['document'] = [
                'story' => $story,
                'dm_notes' => $dmNotes,
            ];
            $state['campaigns'][$campaignId] = $campaign;

            return new JsonResponse([
                'story' => $story,
                'dm_notes' => $dmNotes,
            ]);
        });
    }

    public function getDocument(Request $request, string $campaignId): JsonResponse
    {
        $actor = $this->requireActor($request);
        if ($actor instanceof JsonResponse) {
            return $actor;
        }

        return $this->withCampaigns(function (array &$state) use ($campaignId, $actor) {
            $campaign = self::findCampaign($state, $campaignId);
            if ($campaign === null) {
                return Json::error('campaign not found', 404);
            }

            $isOwner = self::isOwner($campaign, $actor['username']);
            if (!$isOwner && !self::isMember($campaign, $actor['username'])) {
                return Json::error('forbidden', 403);
            }

            $document = $campaign['document'] ?? ['story' => '', 'dm_notes' => ''];

            if ($isOwner) {
                return new JsonResponse([
                    'story' => $document['story'],
                    'dm_notes' => $document['dm_notes'],
                ]);
            }

            return new JsonResponse([
                'story' => $document['story'],
            ]);
        });
    }

    public function gmStatus(Request $request, string $campaignId): JsonResponse
    {
        $actor = $this->requireActor($request);
        if ($actor instanceof JsonResponse) {
            return $actor;
        }

        return $this->withCampaigns(function (array &$state) use ($campaignId, $actor) {
            $campaign = self::findCampaign($state, $campaignId);
            if ($campaign === null) {
                return Json::error('campaign not found', 404);
            }

            if (!self::isOwner($campaign, $actor['username'])) {
                return Json::error('forbidden', 403);
            }

            $currentActor = $campaign['current_actor'] ?? null;

            $party = [];
            foreach ($campaign['members'] ?? [] as $member) {
                $party[] = [
                    'username' => $member['username'],
                    'character_id' => $member['character_id'],
                    'name' => $member['name'],
                    'class' => $member['class'],
                ];
            }

            return new JsonResponse([
                'campaign_id' => $campaign['id'],
                'needs_attention' => $currentActor === $campaign['owner'],
                'current_actor' => $currentActor,
                'party' => $party,
                'recent_events' => $campaign['events'] ?? [],
            ]);
        });
    }

    public function createScene(Request $request, array $body, string $campaignId): JsonResponse
    {
        $actor = $this->requireActor($request);
        if ($actor instanceof JsonResponse) {
            return $actor;
        }

        $id = $body['id'] ?? null;
        $name = $body['name'] ?? null;

        if (!Validators::isValidId($id) || !is_string($name) || $name === '') {
            return Json::error('invalid request');
        }

        return $this->withCampaigns(function (array &$state) use ($campaignId, $actor, $id, $name) {
            $campaign = self::findCampaign($state, $campaignId);
            if ($campaign === null) {
                return Json::error('campaign not found', 404);
            }

            if (!self::isOwner($campaign, $actor['username'])) {
                return Json::error('forbidden', 403);
            }

            $scenes = $campaign['scenes'] ?? [];
            if (isset($scenes[$id])) {
                return Json::error('scene already exists', 409);
            }

            $scene = [
                'id' => $id,
                'name' => $name,
                'status' => 'open',
            ];
            $scenes[$id] = $scene;
            $campaign['scenes'] = $scenes;
            $state['campaigns'][$campaignId] = $campaign;

            return new JsonResponse($scene, 201);
        });
    }

    public function enterScene(Request $request, string $campaignId, string $sceneId): JsonResponse
    {
        $actor = $this->requireActor($request);
        if ($actor instanceof JsonResponse) {
            return $actor;
        }

        return $this->withCampaigns(function (array &$state) use ($campaignId, $actor, $sceneId) {
            $campaign = self::findCampaign($state, $campaignId);
            if ($campaign === null) {
                return Json::error('campaign not found', 404);
            }

            if (!self::isOwner($campaign, $actor['username'])) {
                return Json::error('forbidden', 403);
            }

            $scene = ($campaign['scenes'] ?? [])[$sceneId] ?? null;
            if ($scene === null) {
                return Json::error('scene not found', 404);
            }

            if ($scene['status'] !== 'open') {
                return Json::error('conflict', 409);
            }

            $campaign['current_scene_id'] = $sceneId;

            $events = $campaign['events'] ?? [];
            $events[] = [
                'sequence' => count($events) + 1,
                'kind' => 'scene',
                'actor' => $actor['username'],
                'scene_id' => $sceneId,
            ];
            $campaign['events'] = $events;

            $state['campaigns'][$campaignId] = $campaign;

            return new JsonResponse([
                'current_scene_id' => $sceneId,
                'name' => $scene['name'],
            ]);
        });
    }

    public function closeScene(Request $request, string $campaignId, string $sceneId): JsonResponse
    {
        $actor = $this->requireActor($request);
        if ($actor instanceof JsonResponse) {
            return $actor;
        }

        return $this->withCampaigns(function (array &$state) use ($campaignId, $actor, $sceneId) {
            $campaign = self::findCampaign($state, $campaignId);
            if ($campaign === null) {
                return Json::error('campaign not found', 404);
            }

            if (!self::isOwner($campaign, $actor['username'])) {
                return Json::error('forbidden', 403);
            }

            $scenes = $campaign['scenes'] ?? [];
            $scene = $scenes[$sceneId] ?? null;
            if ($scene === null) {
                return Json::error('scene not found', 404);
            }

            $scene['status'] = 'closed';
            $scenes[$sceneId] = $scene;
            $campaign['scenes'] = $scenes;
            $state['campaigns'][$campaignId] = $campaign;

            return new JsonResponse([
                'id' => $scene['id'],
                'status' => $scene['status'],
            ]);
        });
    }

    public function getCurrentScene(Request $request, string $campaignId): JsonResponse
    {
        $actor = $this->requireActor($request);
        if ($actor instanceof JsonResponse) {
            return $actor;
        }

        return $this->withCampaigns(function (array &$state) use ($campaignId, $actor) {
            $campaign = self::findCampaign($state, $campaignId);
            if ($campaign === null) {
                return Json::error('campaign not found', 404);
            }

            if (!self::isParticipant($campaign, $actor['username'])) {
                return Json::error('forbidden', 403);
            }

            $currentSceneId = $campaign['current_scene_id'] ?? null;
            $scene = $currentSceneId !== null ? ($campaign['scenes'][$currentSceneId] ?? null) : null;

            if ($scene === null || $scene['status'] !== 'open') {
                return Json::error('not found', 404);
            }

            return new JsonResponse([
                'id' => $scene['id'],
                'name' => $scene['name'],
                'status' => $scene['status'],
            ]);
        });
    }

    public function createLocation(Request $request, array $body, string $campaignId): JsonResponse
    {
        $actor = $this->requireActor($request);
        if ($actor instanceof JsonResponse) {
            return $actor;
        }

        $id = $body['id'] ?? null;
        $name = $body['name'] ?? null;

        if (!Validators::isValidId($id) || !is_string($name) || $name === '') {
            return Json::error('invalid request');
        }

        return $this->withCampaigns(function (array &$state) use ($campaignId, $actor, $id, $name) {
            $campaign = self::findCampaign($state, $campaignId);
            if ($campaign === null) {
                return Json::error('campaign not found', 404);
            }

            if (!self::isOwner($campaign, $actor['username'])) {
                return Json::error('forbidden', 403);
            }

            $locations = $campaign['locations'] ?? [];
            if (isset($locations[$id])) {
                return Json::error('location already exists', 409);
            }

            $location = [
                'id' => $id,
                'name' => $name,
            ];
            $locations[$id] = $location;
            $campaign['locations'] = $locations;
            if (!isset($campaign['current_location_id'])) {
                $campaign['current_location_id'] = $id;
            }
            $state['campaigns'][$campaignId] = $campaign;

            return new JsonResponse($location, 201);
        });
    }

    public function createConnection(Request $request, array $body, string $campaignId, string $fromId): JsonResponse
    {
        $actor = $this->requireActor($request);
        if ($actor instanceof JsonResponse) {
            return $actor;
        }

        $toId = $body['to_id'] ?? null;
        $travelTurns = $body['travel_turns'] ?? null;

        if (!Validators::isValidId($toId) || !Validators::isValidInt($travelTurns) || (int) $travelTurns <= 0) {
            return Json::error('invalid request');
        }
        $travelTurns = (int) $travelTurns;

        return $this->withCampaigns(function (array &$state) use ($campaignId, $actor, $fromId, $toId, $travelTurns) {
            $campaign = self::findCampaign($state, $campaignId);
            if ($campaign === null) {
                return Json::error('campaign not found', 404);
            }

            if (!self::isOwner($campaign, $actor['username'])) {
                return Json::error('forbidden', 403);
            }

            $locations = $campaign['locations'] ?? [];
            if (!isset($locations[$fromId]) || !isset($locations[$toId])) {
                return Json::error('invalid request');
            }

            $connections = $campaign['connections'][$fromId] ?? [];
            foreach ($connections as $connection) {
                if ($connection['to_id'] === $toId) {
                    return Json::error('invalid request');
                }
            }

            $connection = [
                'from_id' => $fromId,
                'to_id' => $toId,
                'travel_turns' => $travelTurns,
            ];
            $connections[] = $connection;
            $campaign['connections'][$fromId] = $connections;
            $state['campaigns'][$campaignId] = $campaign;

            return new JsonResponse($connection, 201);
        });
    }

    public function getTravel(Request $request, string $campaignId, string $locId): JsonResponse
    {
        $actor = $this->requireActor($request);
        if ($actor instanceof JsonResponse) {
            return $actor;
        }

        return $this->withCampaigns(function (array &$state) use ($campaignId, $actor, $locId) {
            $campaign = self::findCampaign($state, $campaignId);
            if ($campaign === null) {
                return Json::error('campaign not found', 404);
            }

            if (!self::isParticipant($campaign, $actor['username'])) {
                return Json::error('forbidden', 403);
            }

            $locations = $campaign['locations'] ?? [];
            $connections = $campaign['connections'][$locId] ?? [];

            $destinations = [];
            foreach ($connections as $connection) {
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

            return new JsonResponse(['destinations' => $destinations]);
        });
    }

    public function travelTurn(Request $request, array $body, string $campaignId): JsonResponse
    {
        $actor = $this->requireActor($request);
        if ($actor instanceof JsonResponse) {
            return $actor;
        }

        $destinationId = $body['destination_id'] ?? null;
        if (!Validators::isValidId($destinationId)) {
            return Json::error('invalid request');
        }

        return $this->withCampaigns(function (array &$state) use ($campaignId, $actor, $destinationId) {
            $campaign = self::findCampaign($state, $campaignId);
            if ($campaign === null) {
                return Json::error('campaign not found', 404);
            }

            if (!self::isParticipant($campaign, $actor['username'])) {
                return Json::error('forbidden', 403);
            }

            if ($actor['role'] !== 'player' || $actor['username'] !== ($campaign['current_actor'] ?? null)) {
                return Json::error('conflict', 409);
            }

            $currentLocationId = $campaign['current_location_id'] ?? null;
            $connections = $currentLocationId !== null
                ? ($campaign['connections'][$currentLocationId] ?? [])
                : [];

            $travelTurns = null;
            foreach ($connections as $connection) {
                if ($connection['to_id'] === $destinationId) {
                    $travelTurns = $connection['travel_turns'];
                    break;
                }
            }

            if ($travelTurns === null) {
                return Json::error('conflict', 409);
            }

            $events = $campaign['events'] ?? [];
            $event = [
                'sequence' => count($events) + 1,
                'kind' => 'travel',
                'actor' => $actor['username'],
                'destination_id' => $destinationId,
                'travel_turns' => $travelTurns,
                'next_actor' => 'dm',
            ];
            $events[] = $event;
            $campaign['events'] = $events;
            $campaign['current_location_id'] = $destinationId;
            $campaign['current_actor'] = $campaign['owner'];
            $campaign['phase'] = 'dm';
            $state['campaigns'][$campaignId] = $campaign;

            return new JsonResponse($event, 201);
        });
    }

    public function restTurn(Request $request, array $body, string $campaignId): JsonResponse
    {
        $actor = $this->requireActor($request);
        if ($actor instanceof JsonResponse) {
            return $actor;
        }

        $type = $body['type'] ?? null;
        if ($type !== 'long' && $type !== 'short') {
            return Json::error('invalid request');
        }

        return $this->withCampaigns(function (array &$state) use ($campaignId, $actor, $type) {
            $campaign = self::findCampaign($state, $campaignId);
            if ($campaign === null) {
                return Json::error('campaign not found', 404);
            }

            if (!self::isParticipant($campaign, $actor['username'])) {
                return Json::error('forbidden', 403);
            }

            if ($actor['role'] !== 'player' || $actor['username'] !== ($campaign['current_actor'] ?? null)) {
                return Json::error('conflict', 409);
            }

            $members = $campaign['members'] ?? [];
            $memberIndex = null;
            foreach ($members as $index => $member) {
                if ($member['username'] === $actor['username']) {
                    $memberIndex = $index;
                    break;
                }
            }

            if ($memberIndex === null) {
                return Json::error('conflict', 409);
            }

            $member = $members[$memberIndex];
            if ($type === 'long') {
                $member['hp_current'] = $member['hp_max'];
                $members[$memberIndex] = $member;
                $campaign['members'] = $members;
            }

            $events = $campaign['events'] ?? [];
            $event = [
                'sequence' => count($events) + 1,
                'kind' => 'rest',
                'actor' => $actor['username'],
                'type' => $type,
                'hp_current' => $member['hp_current'],
                'hp_max' => $member['hp_max'],
                'next_actor' => 'dm',
            ];
            $events[] = $event;
            $campaign['events'] = $events;
            $campaign['current_actor'] = $campaign['owner'];
            $campaign['phase'] = 'dm';
            $state['campaigns'][$campaignId] = $campaign;

            return new JsonResponse($event, 201);
        });
    }

    public function createEncounter(Request $request, array $body, string $campaignId): JsonResponse
    {
        $actor = $this->requireActor($request);
        if ($actor instanceof JsonResponse) {
            return $actor;
        }

        $id = $body['id'] ?? null;
        $name = $body['name'] ?? null;

        if (!Validators::isValidId($id) || !is_string($name) || $name === '') {
            return Json::error('invalid request');
        }

        return $this->withCampaigns(function (array &$state) use ($campaignId, $actor, $id, $name) {
            $campaign = self::findCampaign($state, $campaignId);
            if ($campaign === null) {
                return Json::error('campaign not found', 404);
            }

            if (!self::isOwner($campaign, $actor['username'])) {
                return Json::error('forbidden', 403);
            }

            $encounters = $campaign['encounters'] ?? [];
            if (isset($encounters[$id])) {
                return Json::error('encounter already exists', 409);
            }

            if (($campaign['combat_status'] ?? null) === 'active') {
                return Json::error('conflict', 409);
            }

            $encounter = [
                'id' => $id,
                'name' => $name,
                'status' => 'active',
                'combatants' => [],
            ];
            $encounters[$id] = $encounter;
            $campaign['encounters'] = $encounters;
            $campaign['combat_status'] = 'active';
            $campaign['current_encounter_id'] = $id;
            $state['campaigns'][$campaignId] = $campaign;

            return new JsonResponse($encounter, 201);
        });
    }

    public function addMonster(Request $request, array $body, string $campaignId, string $encounterId): JsonResponse
    {
        $actor = $this->requireActor($request);
        if ($actor instanceof JsonResponse) {
            return $actor;
        }

        $monsterId = $body['monster_id'] ?? null;
        $name = $body['name'] ?? null;
        $hpMax = $body['hp_max'] ?? null;
        $initiative = $body['initiative'] ?? null;

        if (!Validators::isValidId($monsterId) || !is_string($name) || $name === ''
            || !Validators::isValidInt($hpMax) || !Validators::isValidInt($initiative)) {
            return Json::error('invalid request');
        }
        $hpMax = (int) $hpMax;
        $initiative = (int) $initiative;

        return $this->withCampaigns(function (array &$state) use ($campaignId, $encounterId, $actor, $monsterId, $name, $hpMax, $initiative) {
            $campaign = self::findCampaign($state, $campaignId);
            if ($campaign === null) {
                return Json::error('campaign not found', 404);
            }

            if (!self::isOwner($campaign, $actor['username'])) {
                return Json::error('forbidden', 403);
            }

            $encounters = $campaign['encounters'] ?? [];
            $encounter = $encounters[$encounterId] ?? null;
            if ($encounter === null) {
                return Json::error('encounter not found', 404);
            }

            $monsters = $encounter['monsters'] ?? [];
            if (isset($monsters[$monsterId])) {
                return Json::error('monster already exists', 409);
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
            $state['campaigns'][$campaignId] = $campaign;

            return new JsonResponse($monster, 201);
        });
    }

    public function removeMonster(Request $request, string $campaignId, string $encounterId, string $monsterId): JsonResponse
    {
        $actor = $this->requireActor($request);
        if ($actor instanceof JsonResponse) {
            return $actor;
        }

        return $this->withCampaigns(function (array &$state) use ($campaignId, $encounterId, $monsterId, $actor) {
            $campaign = self::findCampaign($state, $campaignId);
            if ($campaign === null) {
                return Json::error('campaign not found', 404);
            }

            if (!self::isOwner($campaign, $actor['username'])) {
                return Json::error('forbidden', 403);
            }

            $encounters = $campaign['encounters'] ?? [];
            $encounter = $encounters[$encounterId] ?? null;
            if ($encounter === null) {
                return Json::error('encounter not found', 404);
            }

            $monsters = $encounter['monsters'] ?? [];
            if (!isset($monsters[$monsterId])) {
                return Json::error('monster not found', 404);
            }

            unset($monsters[$monsterId]);
            $encounter['monsters'] = $monsters;
            $encounters[$encounterId] = $encounter;
            $campaign['encounters'] = $encounters;
            $state['campaigns'][$campaignId] = $campaign;

            return new JsonResponse(['removed' => $monsterId], 200);
        });
    }

    public function bindCombatant(Request $request, array $body, string $campaignId, string $encounterId): JsonResponse
    {
        $actor = $this->requireActor($request);
        if ($actor instanceof JsonResponse) {
            return $actor;
        }

        $memberUsername = $body['member'] ?? null;
        $initiative = $body['initiative'] ?? null;

        if (!is_string($memberUsername) || $memberUsername === '' || !Validators::isValidInt($initiative)) {
            return Json::error('invalid request');
        }
        $initiative = (int) $initiative;

        return $this->withCampaigns(function (array &$state) use ($campaignId, $encounterId, $actor, $memberUsername, $initiative) {
            $campaign = self::findCampaign($state, $campaignId);
            if ($campaign === null) {
                return Json::error('campaign not found', 404);
            }

            if (!self::isOwner($campaign, $actor['username'])) {
                return Json::error('forbidden', 403);
            }

            $encounters = $campaign['encounters'] ?? [];
            $encounter = $encounters[$encounterId] ?? null;
            if ($encounter === null) {
                return Json::error('encounter not found', 404);
            }

            $member = self::findMember($campaign, $memberUsername);
            if ($member === null) {
                return Json::error('member not found', 400);
            }

            $combatants = $encounter['combatants'] ?? [];
            if (isset($combatants[$memberUsername])) {
                return Json::error('combatant already exists', 409);
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
            $state['campaigns'][$campaignId] = $campaign;

            return new JsonResponse($combatant, 201);
        });
    }

    public function unbindCombatant(Request $request, string $campaignId, string $encounterId, string $member): JsonResponse
    {
        $actor = $this->requireActor($request);
        if ($actor instanceof JsonResponse) {
            return $actor;
        }

        return $this->withCampaigns(function (array &$state) use ($campaignId, $encounterId, $member, $actor) {
            $campaign = self::findCampaign($state, $campaignId);
            if ($campaign === null) {
                return Json::error('campaign not found', 404);
            }

            if (!self::isOwner($campaign, $actor['username'])) {
                return Json::error('forbidden', 403);
            }

            $encounters = $campaign['encounters'] ?? [];
            $encounter = $encounters[$encounterId] ?? null;
            if ($encounter === null) {
                return Json::error('encounter not found', 404);
            }

            $combatants = $encounter['combatants'] ?? [];
            if (!isset($combatants[$member])) {
                return Json::error('combatant not found', 404);
            }

            unset($combatants[$member]);
            $encounter['combatants'] = $combatants;
            $encounters[$encounterId] = $encounter;
            $campaign['encounters'] = $encounters;
            $state['campaigns'][$campaignId] = $campaign;

            return new JsonResponse(['removed' => $member], 200);
        });
    }

    public function getEncounterTurn(Request $request, string $campaignId, string $encounterId): JsonResponse
    {
        $actor = $this->requireActor($request);
        if ($actor instanceof JsonResponse) {
            return $actor;
        }

        return $this->withCampaigns(function (array &$state) use ($campaignId, $encounterId, $actor) {
            $campaign = self::findCampaign($state, $campaignId);
            if ($campaign === null) {
                return Json::error('campaign not found', 404);
            }

            if (!self::isParticipant($campaign, $actor['username'])) {
                return Json::error('forbidden', 403);
            }

            $encounter = ($campaign['encounters'] ?? [])[$encounterId] ?? null;
            if ($encounter === null) {
                return Json::error('encounter not found', 404);
            }

            $order = self::encounterOrder($encounter);
            if (count($order) === 0) {
                return Json::error('conflict', 409);
            }

            $turnIndex = $encounter['turn_index'] ?? 0;
            if ($turnIndex >= count($order)) {
                $turnIndex = 0;
            }
            $active = $order[$turnIndex];

            return new JsonResponse([
                'round' => $encounter['round'] ?? 1,
                'turn_index' => $turnIndex,
                'active' => [
                    'name' => $active['name'],
                    'kind' => $active['kind'],
                    'initiative' => $active['initiative'],
                ],
            ]);
        });
    }

    public function advanceEncounterTurn(Request $request, string $campaignId, string $encounterId): JsonResponse
    {
        $actor = $this->requireActor($request);
        if ($actor instanceof JsonResponse) {
            return $actor;
        }

        return $this->withCampaigns(function (array &$state) use ($campaignId, $encounterId, $actor) {
            $campaign = self::findCampaign($state, $campaignId);
            if ($campaign === null) {
                return Json::error('campaign not found', 404);
            }

            if (!self::isParticipant($campaign, $actor['username'])) {
                return Json::error('forbidden', 403);
            }

            $encounters = $campaign['encounters'] ?? [];
            $encounter = $encounters[$encounterId] ?? null;
            if ($encounter === null) {
                return Json::error('encounter not found', 404);
            }

            $order = self::encounterOrder($encounter);
            if (count($order) === 0) {
                return Json::error('conflict', 409);
            }

            $turnIndex = $encounter['turn_index'] ?? 0;
            if ($turnIndex >= count($order)) {
                $turnIndex = 0;
            }
            $active = $order[$turnIndex];

            $isOwner = self::isOwner($campaign, $actor['username']);
            $isCurrentCombatant = $active['kind'] === 'player' && $active['ref'] === $actor['username'];
            if (!$isOwner && !$isCurrentCombatant) {
                return Json::error('conflict', 409);
            }

            $count = count($order);
            $round = $encounter['round'] ?? 1;
            $nextIndex = $turnIndex + 1;
            if ($nextIndex >= $count) {
                $nextIndex = 0;
                $round += 1;
            }

            $encounter['turn_index'] = $nextIndex;
            $encounter['round'] = $round;
            $encounters[$encounterId] = $encounter;
            $campaign['encounters'] = $encounters;
            $state['campaigns'][$campaignId] = $campaign;

            $newActive = $order[$nextIndex];

            return new JsonResponse([
                'round' => $round,
                'turn_index' => $nextIndex,
                'active' => [
                    'name' => $newActive['name'],
                    'kind' => $newActive['kind'],
                    'initiative' => $newActive['initiative'],
                ],
            ]);
        });
    }

    /**
     * Combines an encounter's bound party combatants and monsters into a
     * single deterministic initiative order: highest initiative first,
     * ties broken by name so repeated calls are stable.
     */
    private static function encounterOrder(array $encounter): array
    {
        $order = [];
        foreach ($encounter['combatants'] ?? [] as $combatant) {
            $order[] = [
                'name' => $combatant['name'],
                'kind' => 'player',
                'initiative' => $combatant['initiative'],
                'ref' => $combatant['member'],
            ];
        }
        foreach ($encounter['monsters'] ?? [] as $monster) {
            $order[] = [
                'name' => $monster['name'],
                'kind' => 'monster',
                'initiative' => $monster['initiative'],
                'ref' => $monster['monster_id'],
            ];
        }

        usort($order, static function ($a, $b) {
            if ($a['initiative'] !== $b['initiative']) {
                return $b['initiative'] <=> $a['initiative'];
            }
            return $a['name'] <=> $b['name'];
        });

        return $order;
    }

    /** Authenticates the request, returning the actor or a ready-to-send 401 response. */
    private function requireActor(Request $request): array|JsonResponse
    {
        $actor = SessionAuth::authenticate($request);
        if ($actor === null) {
            return Json::error('unauthorized', 401);
        }

        return $actor;
    }

    /** Runs $fn against the shared play-campaigns KV blob, persisting any mutations it makes. */
    private function withCampaigns(callable $fn): JsonResponse
    {
        return KvStore::withState(self::STORE_KEY, ['campaigns' => []], $fn);
    }

    private static function findCampaign(array $state, string $campaignId): ?array
    {
        return $state['campaigns'][$campaignId] ?? null;
    }

    private static function isOwner(array $campaign, string $username): bool
    {
        return $campaign['owner'] === $username;
    }

    private static function isMember(array $campaign, string $username): bool
    {
        return self::findMember($campaign, $username) !== null;
    }

    private static function isParticipant(array $campaign, string $username): bool
    {
        return self::isOwner($campaign, $username) || self::isMember($campaign, $username);
    }

    private static function findMember(array $campaign, string $username): ?array
    {
        foreach ($campaign['members'] ?? [] as $member) {
            if ($member['username'] === $username) {
                return $member;
            }
        }

        return null;
    }

    /**
     * Turn order rotates through party members in join order. The next actor
     * is whoever follows the member who submitted the most recent action
     * event; if no action has happened yet, turn order restarts from the
     * first member.
     */
    private static function nextTurnActor(array $members, array $events): ?string
    {
        $lastActionActor = null;
        for ($i = count($events) - 1; $i >= 0; $i--) {
            if (in_array($events[$i]['kind'] ?? null, ['action', 'travel', 'rest'], true)) {
                $lastActionActor = $events[$i]['actor'];
                break;
            }
        }

        if ($lastActionActor === null) {
            return $members[0]['username'] ?? null;
        }

        foreach ($members as $index => $member) {
            if ($member['username'] === $lastActionActor) {
                return $members[($index + 1) % count($members)]['username'];
            }
        }

        return $members[0]['username'] ?? null;
    }
}
