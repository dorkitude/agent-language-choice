<?php

declare(strict_types=1);

namespace App\Http;

use App\Domain\Calendar;
use App\Domain\CampaignAnalytics;
use App\Domain\CharacterRules;
use App\Domain\Dice;
use App\Domain\Encounter;
use App\Domain\Initiative;
use App\Domain\RestRules;
use App\Domain\RngLedger;
use App\Domain\SpellRules;
use App\Http\ServiceMode;
use App\Storage\GameStorage;
use Symfony\Component\HttpFoundation\JsonResponse;
use Symfony\Component\HttpFoundation\Request;

/**
 * HTTP controllers for the DM tools API.
 *
 * Each public method matches the Symfony callable signature
 * `(Request $request, array $parameters): JsonResponse`. The route parameters
 * have already been stripped of `_controller` and `_route` by the dispatcher.
 *
 * Validation and response-shape rules are preserved from the previous stage.
 */
final class Controllers
{
    public const PLAY_CAMPAIGN_INVENTORY_ITEMS = ['healing-potion', 'torch', 'leather-armor', 'ring-of-protection', 'amulet-of-health'];
    private const EQUIPMENT_ITEMS = ['leather-armor' => 'armor', 'ring-of-protection' => 'accessory', 'amulet-of-health' => 'accessory'];
    private const ATTUNABLE_ITEMS = ['ring-of-protection', 'amulet-of-health'];
    private const MAX_ATTUNEMENTS = 1;

    private AuthHelper $auth;
    private CampaignAnalytics $analytics;

    public function __construct(private GameStorage $storage)
    {
        $this->auth = new AuthHelper($storage);
        $this->analytics = new CampaignAnalytics($storage);
    }

    public function health(Request $request, array $parameters): JsonResponse
    {
        return new JsonResponse(['ok' => true]);
    }

    public function storageStatus(Request $request, array $parameters): JsonResponse
    {
        return new JsonResponse($this->storage->status());
    }

    public function storageReset(Request $request, array $parameters): JsonResponse
    {
        $this->storage->reset();

        return new JsonResponse(['ok' => true, 'schema_version' => 1]);
    }

    public function healthz(Request $request, array $parameters): JsonResponse
    {
        return new JsonResponse(['status' => 'ok']);
    }

    public function schema(Request $request, array $parameters): JsonResponse
    {
        return new JsonResponse(json_encode([
            'version' => '2026-07-29',
            'endpoints' => [
                ['method' => 'GET', 'path' => '/v1/play/campaigns/{id}/rng-ledger', 'auth' => 'member'],
                ['method' => 'GET', 'path' => '/v1/schema', 'auth' => 'public'],
                ['method' => 'POST', 'path' => '/v1/play/campaigns', 'auth' => 'dm'],
                ['method' => 'POST', 'path' => '/v1/play/campaigns/{id}/fixture-seeds', 'auth' => 'dm'],
                ['method' => 'POST', 'path' => '/v1/play/campaigns/{id}/members', 'auth' => 'member'],
                ['method' => 'POST', 'path' => '/v1/play/campaigns/{id}/moderation/reports', 'auth' => 'member'],
                ['method' => 'POST', 'path' => '/v1/play/campaigns/{id}/rng-rolls', 'auth' => 'member'],
                ['method' => 'PUT', 'path' => '/v1/play/campaigns/{id}/moderation/reports/{report_id}/resolution', 'auth' => 'dm'],
                ['method' => 'PUT', 'path' => '/v1/play/campaigns/{id}/rng-seed', 'auth' => 'dm'],
                ['method' => 'PUT', 'path' => '/v1/play/campaigns/{id}/safety-boundaries', 'auth' => 'dm'],
            ],
        ], JSON_UNESCAPED_SLASHES), 200, [], true);
    }

    public function readyz(Request $request, array $parameters): JsonResponse
    {
        if (ServiceMode::isMaintenance()) {
            return new JsonResponse(['status' => 'maintenance', 'schema_version' => 2], 503);
        }

        return new JsonResponse(['status' => 'ready', 'schema_version' => 2]);
    }

    public function setPlayCampaignServiceMode(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireDm($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body) || !array_key_exists('maintenance', $body) || !is_bool($body['maintenance'])) {
            return HttpHelper::error('invalid maintenance flag');
        }

        ServiceMode::setMaintenance($body['maintenance']);

        return new JsonResponse(['maintenance' => ServiceMode::isMaintenance()]);
    }

    public function diceStats(Request $request, array $parameters): JsonResponse
    {
        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body) || !isset($body['expression']) || !is_string($body['expression'])) {
            return HttpHelper::error('invalid expression');
        }

        $parsed = Dice::parse($body['expression']);
        if ($parsed === null) {
            return HttpHelper::error('invalid expression');
        }

        return new JsonResponse(Dice::stats($parsed['count'], $parsed['sides'], $parsed['modifier']));
    }

    public function abilityCheck(Request $request, array $parameters): JsonResponse
    {
        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body)) {
            return HttpHelper::error('invalid json');
        }

        $roll = (int) ($body['roll'] ?? 0);
        $modifier = (int) ($body['modifier'] ?? 0);
        $dc = (int) ($body['dc'] ?? 0);
        $total = $roll + $modifier;

        return new JsonResponse([
            'total' => $total,
            'success' => $total >= $dc,
            'margin' => $total - $dc,
        ]);
    }

    public function adjustedXp(Request $request, array $parameters): JsonResponse
    {
        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body)) {
            return HttpHelper::error('invalid json');
        }

        $party = $body['party'] ?? null;
        $monsters = $body['monsters'] ?? null;
        if (!is_array($party) || !is_array($monsters)) {
            return HttpHelper::error('invalid input');
        }

        $encounterMonsters = [];
        foreach ($monsters as $monster) {
            if (!is_array($monster) || !isset($monster['cr']) || !isset($monster['count'])) {
                return HttpHelper::error('invalid monster');
            }
            $encounterMonsters[] = [
                'cr' => (string) $monster['cr'],
                'count' => (int) $monster['count'],
            ];
        }

        $result = Encounter::calculate($party, $encounterMonsters);
        if (isset($result['error'])) {
            return HttpHelper::error($result['error']);
        }

        return new JsonResponse($result);
    }

    public function initiativeOrder(Request $request, array $parameters): JsonResponse
    {
        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body)) {
            return HttpHelper::error('invalid json');
        }

        $combatants = $body['combatants'] ?? null;
        if (!is_array($combatants)) {
            return HttpHelper::error('invalid input');
        }

        foreach ($combatants as $combatant) {
            if (!is_array($combatant)) {
                return HttpHelper::error('invalid combatant');
            }
        }

        return new JsonResponse(['order' => Initiative::sort($combatants)]);
    }

    public function abilityModifier(Request $request, array $parameters): JsonResponse
    {
        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body) || !isset($body['score']) || !is_int($body['score']) || $body['score'] < 1 || $body['score'] > 30) {
            return HttpHelper::error('invalid score');
        }

        return new JsonResponse([
            'score' => $body['score'],
            'modifier' => CharacterRules::modifier($body['score']),
        ]);
    }

    public function proficiencyBonus(Request $request, array $parameters): JsonResponse
    {
        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body) || !isset($body['level']) || !is_int($body['level']) || $body['level'] < 1 || $body['level'] > 20) {
            return HttpHelper::error('invalid level');
        }

        return new JsonResponse([
            'level' => $body['level'],
            'proficiency_bonus' => CharacterRules::proficiencyBonus($body['level']),
        ]);
    }

    public function derivedStats(Request $request, array $parameters): JsonResponse
    {
        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body)) {
            return HttpHelper::error('invalid json');
        }

        if (!isset($body['level']) || !is_int($body['level']) || $body['level'] < 1 || $body['level'] > 20) {
            return HttpHelper::error('invalid level');
        }
        $level = $body['level'];

        $abilities = $body['abilities'] ?? null;
        $armor = $body['armor'] ?? null;
        $result = CharacterRules::derivedStats($level, $abilities, $armor);
        if (isset($result['error'])) {
            return HttpHelper::error($result['error']);
        }

        return new JsonResponse($result);
    }

    public function createCombatSession(Request $request, array $parameters): JsonResponse
    {
        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body)) {
            return HttpHelper::error('invalid json');
        }
        if (!isset($body['id']) || !is_string($body['id']) || $body['id'] === '') {
            return HttpHelper::error('invalid id');
        }
        $id = $body['id'];

        $combatants = $body['combatants'] ?? null;
        if (!is_array($combatants) || count($combatants) === 0) {
            return HttpHelper::error('invalid combatants');
        }

        foreach ($combatants as $combatant) {
            if (!is_array($combatant)
                || !isset($combatant['name']) || !is_string($combatant['name']) || $combatant['name'] === ''
                || !isset($combatant['dex']) || !is_int($combatant['dex'])
                || !isset($combatant['roll']) || !is_int($combatant['roll'])) {
                return HttpHelper::error('invalid combatant');
            }
        }

        $order = Initiative::sort($combatants);

        if (!$this->storage->createSession($id, $order)) {
            return HttpHelper::error('session already exists');
        }

        return new JsonResponse([
            'id' => $id,
            'round' => 1,
            'turn_index' => 0,
            'active' => $order[0],
            'order' => $order,
        ]);
    }

    public function addCondition(Request $request, array $parameters): JsonResponse
    {
        $id = $parameters['id'] ?? '';
        $session = $this->storage->getSession($id);
        if (!$session) {
            return new JsonResponse(['error' => 'session not found'], 404);
        }

        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body)) {
            return HttpHelper::error('invalid json');
        }
        if (!isset($body['target']) || !is_string($body['target']) || $body['target'] === '') {
            return HttpHelper::error('invalid target');
        }
        $target = $body['target'];

        $found = false;
        foreach ($session['order'] as $combatant) {
            if ($combatant['name'] === $target) {
                $found = true;
                break;
            }
        }
        if (!$found) {
            return HttpHelper::error('invalid target');
        }

        if (!isset($body['condition']) || !is_string($body['condition']) || $body['condition'] === '') {
            return HttpHelper::error('invalid condition');
        }
        if (!isset($body['duration_rounds']) || !is_int($body['duration_rounds']) || $body['duration_rounds'] <= 0) {
            return HttpHelper::error('invalid duration_rounds');
        }

        $this->storage->addCondition($id, $target, $body['condition'], $body['duration_rounds']);

        return new JsonResponse([
            'target' => $target,
            'conditions' => $this->storage->getConditionsForTarget($id, $target),
        ]);
    }

    public function advanceTurn(Request $request, array $parameters): JsonResponse
    {
        $id = $parameters['id'] ?? '';
        $session = $this->storage->advanceTurn($id);
        if (!$session) {
            return new JsonResponse(['error' => 'session not found'], 404);
        }

        return new JsonResponse([
            'id' => $id,
            'round' => $session['round'],
            'turn_index' => $session['turn_index'],
            'active' => $session['order'][$session['turn_index']],
            'conditions' => (object) $session['conditions'],
        ]);
    }

    public function authRegister(Request $request, array $parameters): JsonResponse
    {
        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body)) {
            return HttpHelper::error('invalid json');
        }
        if (!isset($body['username']) || !is_string($body['username'])) {
            return HttpHelper::error('invalid username');
        }
        if (!isset($body['password']) || !is_string($body['password'])) {
            return HttpHelper::error('invalid password');
        }
        if (!isset($body['role']) || !is_string($body['role'])) {
            return HttpHelper::error('invalid role');
        }

        $username = $body['username'];
        $password = $body['password'];
        $role = $body['role'];

        if (!preg_match('/^[a-z0-9_-]{2,32}$/', $username)) {
            return HttpHelper::error('invalid username');
        }
        if (strlen($password) < 8) {
            return HttpHelper::error('invalid password');
        }
        if ($role !== 'dm' && $role !== 'player') {
            return HttpHelper::error('invalid role');
        }
        if ($this->storage->getUser($username) !== null) {
            return new JsonResponse(['error' => 'username already exists'], 409);
        }

        $this->storage->createUser($username, password_hash($password, PASSWORD_DEFAULT), $role);

        return new JsonResponse([
            'username' => $username,
            'role' => $role,
        ], 201);
    }

    public function authLogin(Request $request, array $parameters): JsonResponse
    {
        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body)) {
            return HttpHelper::error('invalid json');
        }
        if (!isset($body['username']) || !is_string($body['username']) || !isset($body['password']) || !is_string($body['password'])) {
            return HttpHelper::error('invalid credentials');
        }

        $username = $body['username'];
        $password = $body['password'];
        $user = $this->storage->getUser($username);
        if ($user === null || !password_verify($password, $user['password_hash'])) {
            return new JsonResponse(['error' => 'invalid credentials'], 401);
        }

        return new JsonResponse([
            'username' => $username,
            'token' => 'session-' . $username,
        ]);
    }

    public function createMonster(Request $request, array $parameters): JsonResponse
    {
        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body)) {
            return HttpHelper::error('invalid json');
        }
        if (!isset($body['slug']) || !is_string($body['slug']) || $body['slug'] === '') {
            return HttpHelper::error('invalid slug');
        }
        if (!isset($body['name']) || !is_string($body['name']) || $body['name'] === '') {
            return HttpHelper::error('invalid name');
        }
        if (!isset($body['cr']) || !is_string($body['cr']) || $body['cr'] === '') {
            return HttpHelper::error('invalid cr');
        }
        if (!isset($body['armor_class']) || !is_int($body['armor_class'])) {
            return HttpHelper::error('invalid armor_class');
        }
        if (!isset($body['hit_points']) || !is_int($body['hit_points'])) {
            return HttpHelper::error('invalid hit_points');
        }
        if (!isset($body['tags']) || !is_array($body['tags'])) {
            return HttpHelper::error('invalid tags');
        }
        foreach ($body['tags'] as $tag) {
            if (!is_string($tag)) {
                return HttpHelper::error('invalid tags');
            }
        }

        $data = [
            'slug' => $body['slug'],
            'name' => $body['name'],
            'cr' => $body['cr'],
            'armor_class' => $body['armor_class'],
            'hit_points' => $body['hit_points'],
            'tags' => array_values($body['tags']),
        ];

        if (!$this->storage->createMonster($data)) {
            return new JsonResponse(['error' => 'slug already exists'], 409);
        }

        return new JsonResponse([
            'slug' => $data['slug'],
            'name' => $data['name'],
            'cr' => $data['cr'],
            'armor_class' => $data['armor_class'],
            'hit_points' => $data['hit_points'],
        ], 201);
    }

    public function readMonster(Request $request, array $parameters): JsonResponse
    {
        $slug = $parameters['slug'] ?? '';
        $monster = $this->storage->getMonster($slug);
        if (!$monster) {
            return new JsonResponse(['error' => 'monster not found'], 404);
        }

        return new JsonResponse($monster);
    }

    public function createItem(Request $request, array $parameters): JsonResponse
    {
        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body)) {
            return HttpHelper::error('invalid json');
        }
        if (!isset($body['slug']) || !is_string($body['slug']) || $body['slug'] === '') {
            return HttpHelper::error('invalid slug');
        }
        if (!isset($body['name']) || !is_string($body['name']) || $body['name'] === '') {
            return HttpHelper::error('invalid name');
        }
        if (!isset($body['type']) || !is_string($body['type']) || $body['type'] === '') {
            return HttpHelper::error('invalid type');
        }
        if (!isset($body['rarity']) || !is_string($body['rarity']) || $body['rarity'] === '') {
            return HttpHelper::error('invalid rarity');
        }
        if (!isset($body['cost_gp']) || !is_int($body['cost_gp'])) {
            return HttpHelper::error('invalid cost_gp');
        }

        $data = [
            'slug' => $body['slug'],
            'name' => $body['name'],
            'type' => $body['type'],
            'rarity' => $body['rarity'],
            'cost_gp' => $body['cost_gp'],
        ];

        if (!$this->storage->createItem($data)) {
            return new JsonResponse(['error' => 'slug already exists'], 409);
        }

        return new JsonResponse($data, 201);
    }

    public function readItem(Request $request, array $parameters): JsonResponse
    {
        $slug = $parameters['slug'] ?? '';
        $item = $this->storage->getItem($slug);
        if (!$item) {
            return new JsonResponse(['error' => 'item not found'], 404);
        }

        return new JsonResponse($item);
    }

    public function createCampaign(Request $request, array $parameters): JsonResponse
    {
        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body)) {
            return HttpHelper::error('invalid json');
        }
        if (!isset($body['id']) || !is_string($body['id']) || $body['id'] === '') {
            return HttpHelper::error('invalid id');
        }
        if (!isset($body['name']) || !is_string($body['name']) || $body['name'] === '') {
            return HttpHelper::error('invalid name');
        }
        if (!isset($body['dm']) || !is_string($body['dm']) || $body['dm'] === '') {
            return HttpHelper::error('invalid dm');
        }

        $data = [
            'id' => $body['id'],
            'name' => $body['name'],
            'dm' => $body['dm'],
        ];

        if (!$this->storage->createCampaign($data)) {
            return new JsonResponse(['error' => 'campaign already exists'], 409);
        }

        return new JsonResponse($data, 201);
    }

    public function addCampaignCharacter(Request $request, array $parameters): JsonResponse
    {
        $campaignId = $parameters['id'] ?? '';
        if ($this->storage->getCampaign($campaignId) === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body)) {
            return HttpHelper::error('invalid json');
        }
        if (!isset($body['id']) || !is_string($body['id']) || $body['id'] === '') {
            return HttpHelper::error('invalid id');
        }
        if (!isset($body['name']) || !is_string($body['name']) || $body['name'] === '') {
            return HttpHelper::error('invalid name');
        }
        if (!isset($body['level']) || !is_int($body['level'])) {
            return HttpHelper::error('invalid level');
        }
        if (!isset($body['class']) || !is_string($body['class']) || $body['class'] === '') {
            return HttpHelper::error('invalid class');
        }

        $data = [
            'id' => $body['id'],
            'name' => $body['name'],
            'level' => $body['level'],
            'class' => $body['class'],
        ];

        if (!$this->storage->createCampaignCharacter($campaignId, $data)) {
            return new JsonResponse(['error' => 'character already exists'], 409);
        }

        return new JsonResponse($data, 201);
    }

    public function addCampaignEvent(Request $request, array $parameters): JsonResponse
    {
        $campaignId = $parameters['id'] ?? '';
        if ($this->storage->getCampaign($campaignId) === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body)) {
            return HttpHelper::error('invalid json');
        }
        if (!isset($body['id']) || !is_string($body['id']) || $body['id'] === '') {
            return HttpHelper::error('invalid id');
        }
        if (!isset($body['kind']) || !is_string($body['kind']) || $body['kind'] === '') {
            return HttpHelper::error('invalid kind');
        }

        $data = [
            'id' => $body['id'],
            'kind' => $body['kind'],
            'summary' => $body['summary'] ?? null,
        ];

        if (!$this->storage->createCampaignEvent($campaignId, $data)) {
            return new JsonResponse(['error' => 'event already exists'], 409);
        }

        return new JsonResponse([
            'id' => $data['id'],
            'kind' => $data['kind'],
        ], 201);
    }

    public function readCampaignState(Request $request, array $parameters): JsonResponse
    {
        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        return new JsonResponse([
            'id' => $campaign['id'],
            'name' => $campaign['name'],
            'dm' => $campaign['dm'],
            'characters' => $this->storage->getCampaignCharacters($campaignId),
            'log_count' => $this->storage->getCampaignEventCount($campaignId),
        ]);
    }

    public function phbSpellSlots(Request $request, array $parameters): JsonResponse
    {
        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body)
            || !isset($body['class']) || !is_string($body['class'])
            || !isset($body['level']) || !is_int($body['level'])) {
            return HttpHelper::error('invalid input');
        }

        $result = RestRules::spellSlots($body['class'], $body['level']);
        if (isset($result['error'])) {
            return HttpHelper::error($result['error']);
        }

        return new JsonResponse($result);
    }

    public function phbLongRest(Request $request, array $parameters): JsonResponse
    {
        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body)) {
            return HttpHelper::error('invalid json');
        }
        foreach (['level', 'hp_current', 'hp_max', 'hit_dice_spent', 'exhaustion_level'] as $key) {
            if (!isset($body[$key]) || !is_int($body[$key])) {
                return HttpHelper::error('invalid input');
            }
        }

        return new JsonResponse(RestRules::longRest(
            $body['level'],
            $body['hp_max'],
            $body['hp_current'],
            $body['hit_dice_spent'],
            $body['exhaustion_level'],
        ));
    }

    public function phbEquipmentLoad(Request $request, array $parameters): JsonResponse
    {
        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body)
            || !isset($body['strength']) || !is_int($body['strength'])
            || !isset($body['weight']) || !is_int($body['weight'])) {
            return HttpHelper::error('invalid input');
        }

        $result = RestRules::equipmentLoad($body['strength'], $body['weight']);
        if (isset($result['error'])) {
            return HttpHelper::error($result['error']);
        }

        return new JsonResponse($result);
    }

    public function dmEncounterBuilder(Request $request, array $parameters): JsonResponse
    {
        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body)) {
            return HttpHelper::error('invalid json');
        }
        if (!isset($body['campaign_id']) || !is_string($body['campaign_id']) || $body['campaign_id'] === '') {
            return HttpHelper::error('invalid campaign_id');
        }

        $campaignId = $body['campaign_id'];
        if ($this->storage->getCampaign($campaignId) === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $party = $body['party'] ?? null;
        if (!is_array($party)) {
            return HttpHelper::error('invalid party');
        }

        $monsterSlugs = $body['monster_slugs'] ?? null;
        if (!is_array($monsterSlugs)) {
            return HttpHelper::error('invalid monster_slugs');
        }

        $crCounts = [];
        foreach ($monsterSlugs as $slug) {
            if (!is_string($slug) || $slug === '') {
                return HttpHelper::error('invalid monster slug');
            }
            if (!isset($crCounts[$slug])) {
                $monster = $this->storage->getMonster($slug);
                if ($monster === null) {
                    return new JsonResponse(['error' => 'monster not found'], 404);
                }
                $cr = (string) $monster['cr'];
                if (!isset(Encounter::xpByCr()[$cr])) {
                    return HttpHelper::error('unsupported cr');
                }
                $crCounts[$slug] = ['cr' => $cr, 'count' => 0];
            }
            $crCounts[$slug]['count']++;
        }

        $monsters = [];
        foreach ($crCounts as $entry) {
            $monsters[] = ['cr' => $entry['cr'], 'count' => $entry['count']];
        }

        $result = Encounter::calculate($party, $monsters);
        if (isset($result['error'])) {
            return HttpHelper::error($result['error']);
        }

        $recommendation = match ($result['difficulty']) {
            'trivial' => 'no challenge',
            'easy' => 'safe warm-up',
            'medium' => 'moderate challenge',
            'hard' => 'hard fight',
            'deadly' => 'deadly encounter',
        };

        return new JsonResponse([
            'campaign_id' => $campaignId,
            'base_xp' => $result['base_xp'],
            'adjusted_xp' => $result['adjusted_xp'],
            'difficulty' => $result['difficulty'],
            'monster_count' => $result['monster_count'],
            'recommendation' => $recommendation,
        ]);
    }

    public function dmLootParcel(Request $request, array $parameters): JsonResponse
    {
        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body)) {
            return HttpHelper::error('invalid json');
        }
        if (!isset($body['campaign_id']) || !is_string($body['campaign_id']) || $body['campaign_id'] === '') {
            return HttpHelper::error('invalid campaign_id');
        }
        if (!isset($body['tier']) || !is_int($body['tier'])) {
            return HttpHelper::error('invalid tier');
        }
        if ($body['tier'] !== 1) {
            return HttpHelper::error('unsupported tier');
        }

        $campaignId = $body['campaign_id'];
        if ($this->storage->getCampaign($campaignId) === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        return new JsonResponse([
            'campaign_id' => $campaignId,
            'coins_gp' => 75,
            'items' => [
                ['slug' => 'healing-potion', 'quantity' => 2],
            ],
        ]);
    }

    public function dmSessionRecap(Request $request, array $parameters): JsonResponse
    {
        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body)) {
            return HttpHelper::error('invalid json');
        }
        if (!isset($body['campaign_id']) || !is_string($body['campaign_id']) || $body['campaign_id'] === '') {
            return HttpHelper::error('invalid campaign_id');
        }

        $campaignId = $body['campaign_id'];
        if ($this->storage->getCampaign($campaignId) === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $event = $this->storage->getLatestCampaignEvent($campaignId);
        $summary = $event['summary'] ?? 'The campaign awaits its next chapter.';
        if ($summary === null) {
            $summary = 'The campaign awaits its next chapter.';
        }

        return new JsonResponse([
            'campaign_id' => $campaignId,
            'summary' => $summary,
            'open_threads' => ['Resolve goblin trail ambush'],
        ]);
    }

    public function createPlayCampaign(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireDm($request);
        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body)) {
            return HttpHelper::error('invalid json');
        }
        if (!isset($body['id']) || !is_string($body['id']) || $body['id'] === '') {
            return HttpHelper::error('invalid id');
        }
        if (!isset($body['name']) || !is_string($body['name']) || $body['name'] === '') {
            return HttpHelper::error('invalid name');
        }
        if (!isset($body['max_players']) || !is_int($body['max_players']) || $body['max_players'] <= 0) {
            return HttpHelper::error('invalid max_players');
        }

        $data = [
            'id' => $body['id'],
            'name' => $body['name'],
            'owner' => $user['username'],
            'status' => 'lobby',
            'max_players' => $body['max_players'],
        ];

        if (!$this->storage->createPlayCampaign($data)) {
            return new JsonResponse(['error' => 'campaign already exists'], 409);
        }

        return new JsonResponse($data, 201);
    }

    public function joinPlayCampaign(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requirePlayer($request);
        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body)) {
            return HttpHelper::error('invalid json');
        }
        if (!isset($body['character_id']) || !is_string($body['character_id']) || $body['character_id'] === '') {
            return HttpHelper::error('invalid character_id');
        }
        if (!isset($body['name']) || !is_string($body['name']) || $body['name'] === '') {
            return HttpHelper::error('invalid name');
        }
        if (!isset($body['class']) || !is_string($body['class']) || $body['class'] === '') {
            return HttpHelper::error('invalid class');
        }

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }
        if ($campaign['status'] !== 'lobby') {
            return new JsonResponse(['error' => 'campaign is not in lobby'], 409);
        }

        $memberCount = $this->storage->getPlayCampaignMemberCount($campaignId);
        if ($memberCount >= $campaign['max_players']) {
            return new JsonResponse(['error' => 'party is full'], 409);
        }

        if (!$this->storage->addPlayCampaignMember($campaignId, $user['username'], $body['character_id'], $body['name'], $body['class'])) {
            return new JsonResponse(['error' => 'membership already exists'], 409);
        }

        return new JsonResponse([
            'username' => $user['username'],
            'character_id' => $body['character_id'],
            'name' => $body['name'],
            'class' => $body['class'],
        ], 201);
    }

    public function startPlayCampaign(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireDm($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $user = $this->auth->requirePlayCampaignOwner($request, $campaign);
        if ($campaign['status'] !== 'lobby') {
            return new JsonResponse(['error' => 'campaign already active'], 409);
        }

        $members = $this->storage->getPlayCampaignMembers($campaignId);
        if (count($members) < 2) {
            return new JsonResponse(['error' => 'insufficient party members'], 409);
        }

        $currentActor = $members[0]['username'];
        if (!$this->storage->startPlayCampaign($campaignId, $currentActor)) {
            return new JsonResponse(['error' => 'campaign already active'], 409);
        }

        return new JsonResponse([
            'id' => $campaignId,
            'status' => 'active',
            'current_actor' => $currentActor,
            'turn_number' => 1,
        ]);
    }

    public function setPlayCampaignSessionZero(Request $request, array $parameters): JsonResponse
    {
        $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $this->auth->requirePlayCampaignOwner($request, $campaign);

        if ($campaign['status'] !== 'lobby') {
            return new JsonResponse(['error' => 'campaign is not in lobby'], 409);
        }

        $body = HttpHelper::parseJsonBody($request);
        $settings = $this->validateSessionZeroPayload($body);
        if ($settings instanceof JsonResponse) {
            return $settings;
        }

        $this->storage->setPlayCampaignSessionZero($campaignId, $settings);

        return new JsonResponse($settings, 200);
    }

    public function getPlayCampaignSessionZero(Request $request, array $parameters): JsonResponse
    {
        $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $this->auth->requirePlayCampaignMemberOrOwner($request, $campaign);

        $settings = $this->storage->getPlayCampaignSessionZero($campaignId);
        if ($settings === null) {
            return new JsonResponse(['error' => 'session zero settings not found'], 404);
        }

        return new JsonResponse($settings);
    }

    public function createPlayCampaignContent(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireDm($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $this->auth->requirePlayCampaignOwner($request, $campaign);

        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body)) {
            return HttpHelper::error('invalid json');
        }
        if (!isset($body['content_id']) || !is_string($body['content_id']) || $body['content_id'] === '') {
            return HttpHelper::error('invalid content_id');
        }
        if (!isset($body['kind']) || !is_string($body['kind']) || $body['kind'] === '') {
            return HttpHelper::error('invalid kind');
        }
        if (!isset($body['text']) || !is_string($body['text']) || $body['text'] === '') {
            return HttpHelper::error('invalid text');
        }
        if (!isset($body['tags']) || !is_array($body['tags']) || count($body['tags']) === 0) {
            return HttpHelper::error('invalid tags');
        }

        $tags = [];
        $seen = [];
        foreach ($body['tags'] as $tag) {
            if (!is_string($tag) || $tag === '') {
                return HttpHelper::error('invalid tags');
            }
            if (isset($seen[$tag])) {
                return HttpHelper::error('invalid tags');
            }
            $seen[$tag] = true;
            $tags[] = $tag;
        }

        if (!$this->storage->createPlayCampaignContent($campaignId, $body['content_id'], $body['kind'], $body['text'], $tags)) {
            return new JsonResponse(['error' => 'content already exists'], 409);
        }

        return new JsonResponse([
            'content_id' => $body['content_id'],
            'kind' => $body['kind'],
            'text' => $body['text'],
            'tags' => $tags,
        ], 201);
    }

    public function updatePlayCampaignContentTags(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireDm($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $this->auth->requirePlayCampaignOwner($request, $campaign);

        $contentId = $parameters['content_id'] ?? '';
        $content = $this->storage->getPlayCampaignContent($campaignId, $contentId);
        if ($content === null) {
            return new JsonResponse(['error' => 'content not found'], 404);
        }

        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body)) {
            return HttpHelper::error('invalid json');
        }
        if (!isset($body['tags']) || !is_array($body['tags'])) {
            return HttpHelper::error('invalid tags');
        }

        $tags = [];
        $seen = [];
        foreach ($body['tags'] as $tag) {
            if (!is_string($tag) || $tag === '') {
                return HttpHelper::error('invalid tags');
            }
            if (isset($seen[$tag])) {
                return HttpHelper::error('invalid tags');
            }
            $seen[$tag] = true;
            $tags[] = $tag;
        }

        $this->storage->updatePlayCampaignContentTags($campaignId, $contentId, $tags);

        return new JsonResponse([
            'content_id' => $content['content_id'],
            'kind' => $content['kind'],
            'text' => $content['text'],
            'tags' => $tags,
        ], 200);
    }

    public function readPlayCampaignOnboarding(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $isOwner = $campaign['owner'] === $user['username'];
        if (!$isOwner && !$this->storage->isPlayCampaignMember($campaignId, $user['username'])) {
            throw new HttpException('forbidden', 403);
        }

        if ($isOwner) {
            return new JsonResponse([
                'role' => 'dm',
                'next_steps' => ['configure-safety', 'invite-players', 'start-campaign'],
                'can_mutate' => true,
            ]);
        }

        return new JsonResponse([
            'role' => 'player',
            'next_steps' => ['review-party', 'take-turn', 'submit-action'],
            'can_mutate' => true,
        ]);
    }

    public function getPlayCampaignContent(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        [$user, $isOwner] = $this->auth->requirePlayCampaignMemberOrOwner($request, $campaign);

        $excludeTag = $request->query->get('exclude_tag');
        if ($excludeTag !== null && (!is_string($excludeTag) || $excludeTag === '')) {
            return HttpHelper::error('invalid exclude_tag');
        }

        $content = $this->storage->getPlayCampaignContentList($campaignId);

        if ($isOwner || $excludeTag === null) {
            return new JsonResponse(['content' => $content]);
        }

        $filtered = [];
        foreach ($content as $item) {
            if (!in_array($excludeTag, $item['tags'], true)) {
                $filtered[] = $item;
            }
        }

        return new JsonResponse(['content' => $filtered]);
    }

    public function addPlayCampaignNarration(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $isOwner = $campaign['owner'] === $user['username'];
        $canNarrate = $isOwner || $this->storage->hasPlayCampaignDelegationPower($campaignId, $user['username'], 'narrate');
        if (!$canNarrate) {
            return new JsonResponse(['error' => 'forbidden'], 403);
        }

        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body)) {
            return HttpHelper::error('invalid json');
        }
        if (!isset($body['text']) || !is_string($body['text']) || $body['text'] === '') {
            return HttpHelper::error('invalid text');
        }

        $event = $this->storage->addPlayCampaignNarration($campaignId, $user['username'], $body['text']);

        return new JsonResponse($event, 201);
    }

    public function nudgePlayCampaignTurn(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $user = $this->auth->requirePlayCampaignOwner($request, $campaign);

        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body) || !isset($body['message']) || !is_string($body['message']) || $body['message'] === '') {
            return HttpHelper::error('invalid message');
        }

        $result = $this->storage->addPlayCampaignNudge($campaignId, $user['username'], $campaign['current_actor'], $body['message']);

        return new JsonResponse($result, 201);
    }

    public function getPlayCampaignTurn(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        [$user, $isOwner] = $this->auth->requirePlayCampaignMemberOrOwner($request, $campaign);

        $members = $this->storage->getPlayCampaignMembers($campaignId);
        $queue = [];
        foreach ($members as $member) {
            $queue[] = $member['username'];
            $queue[] = $campaign['owner'];
        }

        if ($campaign['status'] !== 'active') {
            $phase = 'lobby';
        } elseif (isset($campaign['phase']) && $campaign['phase'] !== null && $campaign['phase'] !== '') {
            $phase = $campaign['phase'];
        } elseif ($campaign['current_actor'] === $campaign['owner']) {
            $phase = 'dm';
        } else {
            $phase = 'player';
        }

        return new JsonResponse([
            'campaign_id' => $campaignId,
            'current_actor' => $campaign['current_actor'],
            'phase' => $phase,
            'turn_number' => $campaign['turn_number'],
            'queue' => $queue,
            'overdue' => false,
            'logical_deadline' => $campaign['turn_number'] + 1,
        ]);
    }

    public function getPlayCampaignMyTurn(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requirePlayer($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }
        if (!$this->storage->isPlayCampaignMember($campaignId, $user['username'])) {
            return new JsonResponse(['error' => 'forbidden'], 403);
        }

        $member = $this->storage->getPlayCampaignMember($campaignId, $user['username']);
        if ($member === null) {
            return new JsonResponse(['error' => 'forbidden'], 403);
        }

        $isMyTurn = $campaign['current_actor'] === $user['username'];

        return new JsonResponse([
            'is_my_turn' => $isMyTurn,
            'current_actor' => $campaign['current_actor'],
            'character' => [
                'id' => $member['character_id'],
                'name' => $member['name'],
            ],
            'recent_events' => $this->storage->getPlayCampaignNarrations($campaignId),
        ]);
    }

    public function getPlayCampaignGmStatus(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $user = $this->auth->requirePlayCampaignOwner($request, $campaign);

        $members = $this->storage->getPlayCampaignMembers($campaignId);
        $party = [];
        foreach ($members as $member) {
            $party[] = [
                'username' => $member['username'],
                'character_id' => $member['character_id'],
                'name' => $member['name'],
                'class' => $member['class'],
            ];
        }

        return new JsonResponse([
            'needs_attention' => $campaign['current_actor'] === $campaign['owner'],
            'current_actor' => $campaign['current_actor'],
            'party' => $party,
            'recent_events' => $this->storage->getPlayCampaignNarrations($campaignId),
        ]);
    }

    public function submitPlayCampaignAction(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requirePlayerOrConflict($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }
        if (!$this->storage->isPlayCampaignMember($campaignId, $user['username'])) {
            return new JsonResponse(['error' => 'forbidden'], 403);
        }

        if ($campaign['current_actor'] !== $user['username']) {
            return new JsonResponse(['error' => 'conflict'], 409);
        }

        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body)) {
            return HttpHelper::error('invalid json');
        }
        if (!isset($body['type']) || !is_string($body['type']) || $body['type'] === '') {
            return HttpHelper::error('invalid type');
        }
        if (!isset($body['text']) || !is_string($body['text']) || $body['text'] === '') {
            return HttpHelper::error('invalid text');
        }

        $event = $this->storage->addPlayCampaignAction($campaignId, $user['username'], $body['type'], $body['text']);
        $this->storage->setPlayCampaignCurrentActor($campaignId, $campaign['owner']);

        return new JsonResponse([
            'sequence' => $event['sequence'],
            'kind' => $event['kind'],
            'actor' => $event['actor'],
            'type' => $event['type'],
            'text' => $event['text'],
            'next_actor' => 'dm',
        ], 201);
    }

    public function resolvePlayCampaignAction(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        [$user, $isOwner] = $this->auth->requirePlayCampaignMemberOrOwner($request, $campaign);

        if (!$isOwner || $campaign['current_actor'] !== $campaign['owner']) {
            return new JsonResponse(['error' => 'conflict'], 409);
        }

        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body)) {
            return HttpHelper::error('invalid json');
        }
        if (!isset($body['text']) || !is_string($body['text']) || $body['text'] === '') {
            return HttpHelper::error('invalid text');
        }

        $members = $this->storage->getPlayCampaignMembers($campaignId);
        if (count($members) < 2) {
            return new JsonResponse(['error' => 'conflict'], 409);
        }

        $nextActor = $campaign['turn_number'] >= 2 ? $members[0]['username'] : $members[1]['username'];

        $result = $this->storage->addPlayCampaignResolution($campaignId, $user['username'], $body['text'], $nextActor);
        $event = $result['event'];

        return new JsonResponse([
            'sequence' => $event['sequence'],
            'kind' => $event['kind'],
            'actor' => $event['actor'],
            'text' => $event['text'],
            'next_actor' => $result['next_actor'],
            'turn_number' => $result['turn_number'],
        ], 201);
    }

    public function updatePlayCampaignDocument(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $user = $this->auth->requirePlayCampaignOwner($request, $campaign);

        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body)) {
            return HttpHelper::error('invalid json');
        }
        if (!isset($body['story']) || !is_string($body['story'])) {
            return HttpHelper::error('invalid story');
        }
        if (!isset($body['dm_notes']) || !is_string($body['dm_notes'])) {
            return HttpHelper::error('invalid dm_notes');
        }

        $this->storage->setPlayCampaignDocument($campaignId, $body['story'], $body['dm_notes']);

        return new JsonResponse([
            'story' => $body['story'],
            'dm_notes' => $body['dm_notes'],
        ]);
    }

    public function getPlayCampaignDocument(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        [$user, $isOwner] = $this->auth->requirePlayCampaignMemberOrOwner($request, $campaign);

        $document = $this->storage->getPlayCampaignDocument($campaignId);

        if ($isOwner) {
            return new JsonResponse([
                'story' => $document['story'],
                'dm_notes' => $document['dm_notes'],
            ]);
        }

        return new JsonResponse([
            'story' => $document['story'],
        ]);
    }

    public function createPlayCampaignExport(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }
        if ($campaign['owner'] !== $user['username']) {
            throw new HttpException('forbidden', 403);
        }

        $export = $this->storage->createPlayCampaignExport($campaignId);
        if ($export === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        return new JsonResponse($export, 201);
    }

    public function listPlayCampaignExports(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }
        if ($campaign['owner'] !== $user['username']) {
            throw new HttpException('forbidden', 403);
        }

        return new JsonResponse(['exports' => $this->storage->getPlayCampaignExports($campaignId)]);
    }

    public function getPlayCampaignExport(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }
        if ($campaign['owner'] !== $user['username']) {
            throw new HttpException('forbidden', 403);
        }

        $version = (int) ($parameters['version'] ?? 0);
        $export = $this->storage->getPlayCampaignExport($campaignId, $version);
        if ($export === null) {
            return new JsonResponse(['error' => 'export not found'], 404);
        }

        return new JsonResponse($export);
    }

    public function createQuest(Request $request, array $parameters): JsonResponse
    {
        $campaignId = $parameters['id'] ?? '';
        if ($this->storage->getCampaign($campaignId) === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body)) {
            return HttpHelper::error('invalid json');
        }
        if (!isset($body['id']) || !is_string($body['id']) || $body['id'] === '') {
            return HttpHelper::error('invalid id');
        }
        if (!isset($body['title']) || !is_string($body['title']) || $body['title'] === '') {
            return HttpHelper::error('invalid title');
        }
        if (!isset($body['status']) || !is_string($body['status']) || $body['status'] === '') {
            return HttpHelper::error('invalid status');
        }
        if (!isset($body['milestones']) || !is_array($body['milestones']) || count($body['milestones']) === 0) {
            return HttpHelper::error('invalid milestones');
        }
        foreach ($body['milestones'] as $milestone) {
            if (!is_string($milestone) || $milestone === '') {
                return HttpHelper::error('invalid milestones');
            }
        }

        $data = [
            'id' => $body['id'],
            'title' => $body['title'],
            'status' => $body['status'],
            'milestones' => array_values($body['milestones']),
        ];

        if (!$this->storage->createQuest($campaignId, $data)) {
            return new JsonResponse(['error' => 'quest already exists'], 409);
        }

        $quest = $this->storage->getQuest($data['id']);

        return new JsonResponse([
            'id' => $quest['id'],
            'title' => $quest['title'],
            'status' => $quest['status'],
            'milestones_total' => $quest['milestones_total'],
            'milestones_done' => $quest['milestones_done'],
        ], 201);
    }

    public function updateQuestProgress(Request $request, array $parameters): JsonResponse
    {
        $campaignId = $parameters['id'] ?? '';
        $questId = $parameters['quest_id'] ?? '';

        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body)) {
            return HttpHelper::error('invalid json');
        }
        if (!isset($body['completed']) || !is_array($body['completed'])) {
            return HttpHelper::error('invalid completed');
        }
        foreach ($body['completed'] as $milestone) {
            if (!is_string($milestone)) {
                return HttpHelper::error('invalid completed');
            }
        }

        $quest = $this->storage->updateQuestProgress($campaignId, $questId, array_values($body['completed']));
        if ($quest === null) {
            return new JsonResponse(['error' => 'quest not found'], 404);
        }

        return new JsonResponse([
            'id' => $quest['id'],
            'status' => $quest['status'],
            'milestones_total' => $quest['milestones_total'],
            'milestones_done' => $quest['milestones_done'],
        ]);
    }

    public function getQuestSummary(Request $request, array $parameters): JsonResponse
    {
        $campaignId = $parameters['id'] ?? '';
        if ($this->storage->getCampaign($campaignId) === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        return new JsonResponse($this->storage->getQuestSummary($campaignId));
    }

    public function createFaction(Request $request, array $parameters): JsonResponse
    {
        $campaignId = $parameters['id'] ?? '';
        if ($this->storage->getCampaign($campaignId) === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body)) {
            return HttpHelper::error('invalid json');
        }
        if (!isset($body['id']) || !is_string($body['id']) || $body['id'] === '') {
            return HttpHelper::error('invalid id');
        }
        if (!isset($body['name']) || !is_string($body['name']) || $body['name'] === '') {
            return HttpHelper::error('invalid name');
        }
        if (!isset($body['stance']) || !is_string($body['stance']) || $body['stance'] === '') {
            return HttpHelper::error('invalid stance');
        }

        $data = [
            'id' => $body['id'],
            'name' => $body['name'],
            'stance' => $body['stance'],
        ];

        if (!$this->storage->createFaction($campaignId, $data)) {
            return new JsonResponse(['error' => 'faction already exists'], 409);
        }

        return new JsonResponse($data, 201);
    }

    public function createNpc(Request $request, array $parameters): JsonResponse
    {
        $campaignId = $parameters['id'] ?? '';
        if ($this->storage->getCampaign($campaignId) === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body)) {
            return HttpHelper::error('invalid json');
        }
        if (!isset($body['id']) || !is_string($body['id']) || $body['id'] === '') {
            return HttpHelper::error('invalid id');
        }
        if (!isset($body['name']) || !is_string($body['name']) || $body['name'] === '') {
            return HttpHelper::error('invalid name');
        }
        if (!isset($body['faction_id']) || !is_string($body['faction_id']) || $body['faction_id'] === '') {
            return HttpHelper::error('invalid faction_id');
        }
        if ($this->storage->getFaction($campaignId, $body['faction_id']) === null) {
            return HttpHelper::error('invalid faction_id');
        }
        if (!isset($body['disposition']) || !is_int($body['disposition'])) {
            return HttpHelper::error('invalid disposition');
        }

        $data = [
            'id' => $body['id'],
            'name' => $body['name'],
            'faction_id' => $body['faction_id'],
            'disposition' => $body['disposition'],
        ];

        if (!$this->storage->createNpc($campaignId, $data)) {
            return new JsonResponse(['error' => 'npc already exists'], 409);
        }

        return new JsonResponse($data, 201);
    }

    public function readRelationships(Request $request, array $parameters): JsonResponse
    {
        $campaignId = $parameters['id'] ?? '';
        if ($this->storage->getCampaign($campaignId) === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        return new JsonResponse($this->storage->getRelationshipSummary($campaignId));
    }

    public function addInventoryItem(Request $request, array $parameters): JsonResponse
    {
        $campaignId = $parameters['id'] ?? '';
        if ($this->storage->getCampaign($campaignId) === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body)) {
            return HttpHelper::error('invalid json');
        }
        if (!isset($body['item_slug']) || !is_string($body['item_slug']) || $body['item_slug'] === '') {
            return HttpHelper::error('invalid item_slug');
        }
        if (!isset($body['quantity']) || !is_int($body['quantity']) || $body['quantity'] <= 0) {
            return HttpHelper::error('invalid quantity');
        }
        if (!isset($body['owner']) || !is_string($body['owner']) || $body['owner'] === '') {
            return HttpHelper::error('invalid owner');
        }

        $itemSlug = $body['item_slug'];
        $quantity = $body['quantity'];
        $owner = $body['owner'];

        if ($owner !== 'party') {
            if ($this->storage->getCampaignCharacter($campaignId, $owner) === null) {
                return new JsonResponse(['error' => 'character not found'], 404);
            }
        }

        $this->storage->addInventoryItem($campaignId, $itemSlug, $quantity, $owner, 'entry');

        return new JsonResponse([
            'item_slug' => $itemSlug,
            'quantity' => $quantity,
            'owner' => $owner,
        ], 201);
    }

    public function assignEquipment(Request $request, array $parameters): JsonResponse
    {
        $campaignId = $parameters['id'] ?? '';
        $characterId = $parameters['character_id'] ?? '';

        if ($this->storage->getCampaign($campaignId) === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }
        if ($this->storage->getCampaignCharacter($campaignId, $characterId) === null) {
            return new JsonResponse(['error' => 'character not found'], 404);
        }

        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body)) {
            return HttpHelper::error('invalid json');
        }
        if (!isset($body['item_slug']) || !is_string($body['item_slug']) || $body['item_slug'] === '') {
            return HttpHelper::error('invalid item_slug');
        }
        if (!isset($body['quantity']) || !is_int($body['quantity']) || $body['quantity'] <= 0) {
            return HttpHelper::error('invalid quantity');
        }

        $itemSlug = $body['item_slug'];
        $quantity = $body['quantity'];

        if (!$this->storage->hasAvailablePartyQuantity($campaignId, $itemSlug, $quantity)) {
            return HttpHelper::error('insufficient quantity');
        }

        $this->storage->addInventoryItem($campaignId, $itemSlug, $quantity, $characterId, 'assignment');

        return new JsonResponse([
            'character_id' => $characterId,
            'item_slug' => $itemSlug,
            'quantity' => $quantity,
        ], 200);
    }

    public function getInventorySummary(Request $request, array $parameters): JsonResponse
    {
        $campaignId = $parameters['id'] ?? '';
        if ($this->storage->getCampaign($campaignId) === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        return new JsonResponse($this->storage->getInventorySummary($campaignId));
    }

    public function createCraftingProject(Request $request, array $parameters): JsonResponse
    {
        $campaignId = $parameters['id'] ?? '';
        if ($this->storage->getCampaign($campaignId) === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body)) {
            return HttpHelper::error('invalid json');
        }
        if (!isset($body['id']) || !is_string($body['id']) || $body['id'] === '') {
            return HttpHelper::error('invalid id');
        }
        if (!isset($body['character_id']) || !is_string($body['character_id']) || $body['character_id'] === '') {
            return HttpHelper::error('invalid character_id');
        }
        if (!isset($body['item_slug']) || !is_string($body['item_slug']) || $body['item_slug'] === '') {
            return HttpHelper::error('invalid item_slug');
        }
        if (!isset($body['days_required']) || !is_int($body['days_required']) || $body['days_required'] <= 0) {
            return HttpHelper::error('invalid days_required');
        }
        if (!isset($body['cost_gp']) || !is_int($body['cost_gp']) || $body['cost_gp'] < 0) {
            return HttpHelper::error('invalid cost_gp');
        }

        $data = [
            'id' => $body['id'],
            'campaign_id' => $campaignId,
            'character_id' => $body['character_id'],
            'item_slug' => $body['item_slug'],
            'days_required' => $body['days_required'],
            'cost_gp' => $body['cost_gp'],
        ];

        if (!$this->storage->createCraftingProject($data)) {
            return new JsonResponse(['error' => 'project already exists'], 409);
        }

        return new JsonResponse([
            'id' => $data['id'],
            'character_id' => $data['character_id'],
            'item_slug' => $data['item_slug'],
            'days_required' => $data['days_required'],
            'days_completed' => 0,
            'status' => 'active',
        ], 201);
    }

    public function advanceCraftingProject(Request $request, array $parameters): JsonResponse
    {
        $campaignId = $parameters['id'] ?? '';
        $projectId = $parameters['project_id'] ?? '';

        if ($this->storage->getCampaign($campaignId) === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $project = $this->storage->getCraftingProject($projectId);
        if (!$project || $project['campaign_id'] !== $campaignId) {
            return new JsonResponse(['error' => 'project not found'], 404);
        }

        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body)) {
            return HttpHelper::error('invalid json');
        }
        if (!isset($body['days']) || !is_int($body['days']) || $body['days'] <= 0) {
            return HttpHelper::error('invalid days');
        }

        if ($project['status'] === 'complete') {
            return HttpHelper::error('project already complete');
        }

        $updated = $this->storage->advanceCraftingProject($projectId, $body['days']);
        if (!$updated) {
            return new JsonResponse(['error' => 'project not found'], 404);
        }

        if ($updated['status'] === 'complete') {
            $this->storage->addInventoryItem($campaignId, $updated['item_slug'], 1, 'party', 'crafting');
        }

        return new JsonResponse([
            'id' => $updated['id'],
            'days_completed' => $updated['days_completed'],
            'status' => $updated['status'],
        ]);
    }

    public function scheduleSession(Request $request, array $parameters): JsonResponse
    {
        $campaignId = $parameters['id'] ?? '';
        if ($this->storage->getCampaign($campaignId) === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body)) {
            return HttpHelper::error('invalid json');
        }
        if (!isset($body['id']) || !is_string($body['id']) || $body['id'] === '') {
            return HttpHelper::error('invalid id');
        }
        if (!isset($body['starts_at']) || !is_string($body['starts_at']) || $body['starts_at'] === '') {
            return HttpHelper::error('invalid starts_at');
        }
        if (!isset($body['duration_minutes']) || !is_int($body['duration_minutes']) || $body['duration_minutes'] <= 0) {
            return HttpHelper::error('invalid duration_minutes');
        }
        if (!isset($body['agenda']) || !is_array($body['agenda'])) {
            return HttpHelper::error('invalid agenda');
        }
        foreach ($body['agenda'] as $item) {
            if (!is_string($item)) {
                return HttpHelper::error('invalid agenda');
            }
        }

        $data = [
            'id' => $body['id'],
            'starts_at' => $body['starts_at'],
            'duration_minutes' => $body['duration_minutes'],
            'agenda' => array_values($body['agenda']),
        ];

        if (!$this->storage->createCampaignSession($campaignId, $data)) {
            return new JsonResponse(['error' => 'session already exists'], 409);
        }

        return new JsonResponse([
            'id' => $data['id'],
            'starts_at' => $data['starts_at'],
            'duration_minutes' => $data['duration_minutes'],
            'agenda_count' => count($data['agenda']),
        ], 201);
    }

    public function recordAttendance(Request $request, array $parameters): JsonResponse
    {
        $campaignId = $parameters['id'] ?? '';
        $sessionId = $parameters['session_id'] ?? '';

        if ($this->storage->getCampaign($campaignId) === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body)) {
            return HttpHelper::error('invalid json');
        }
        if (!isset($body['present']) || !is_array($body['present'])) {
            return HttpHelper::error('invalid present');
        }
        if (!isset($body['absent']) || !is_array($body['absent'])) {
            return HttpHelper::error('invalid absent');
        }
        foreach ($body['present'] as $characterId) {
            if (!is_string($characterId)) {
                return HttpHelper::error('invalid present');
            }
        }
        foreach ($body['absent'] as $characterId) {
            if (!is_string($characterId)) {
                return HttpHelper::error('invalid absent');
            }
        }

        $result = $this->storage->recordAttendance($campaignId, $sessionId, array_values($body['present']), array_values($body['absent']));
        if ($result === null) {
            return new JsonResponse(['error' => 'session not found'], 404);
        }

        return new JsonResponse($result);
    }

    public function getNextSession(Request $request, array $parameters): JsonResponse
    {
        $campaignId = $parameters['id'] ?? '';
        if ($this->storage->getCampaign($campaignId) === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $session = $this->storage->getNextCampaignSession($campaignId);
        if ($session === null) {
            return new JsonResponse(['error' => 'session not found'], 404);
        }

        return new JsonResponse([
            'id' => $session['id'],
            'starts_at' => $session['starts_at'],
            'agenda_count' => count($session['agenda']),
        ]);
    }

    public function auditCampaign(Request $request, array $parameters): JsonResponse
    {
        $campaignId = $parameters['id'] ?? '';
        if ($this->storage->getCampaign($campaignId) === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        return new JsonResponse([
            'campaign_id' => $campaignId,
            'events' => $this->storage->getCampaignEventCount($campaignId),
            'quests' => $this->storage->getCampaignQuestCount($campaignId),
            'npcs' => $this->storage->getCampaignNpcCount($campaignId),
            'sessions' => $this->storage->getCampaignSessionCount($campaignId),
        ]);
    }

    public function exportCampaign(Request $request, array $parameters): JsonResponse
    {
        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        return new JsonResponse([
            'campaign_id' => $campaignId,
            'name' => $campaign['name'],
            'characters' => $this->storage->getCampaignCharacterCount($campaignId),
            'quests' => $this->storage->getCampaignQuestCount($campaignId),
            'npcs' => $this->storage->getCampaignNpcCount($campaignId),
            'inventory_items' => $this->storage->getCampaignInventoryItemCount($campaignId),
            'sessions' => $this->storage->getCampaignSessionCount($campaignId),
            'schema_version' => $this->storage->getSchemaVersion(),
        ]);
    }

    public function campaignAnalyticsSummary(Request $request, array $parameters): JsonResponse
    {
        $campaignId = $parameters['id'] ?? '';
        if ($this->storage->getCampaign($campaignId) === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        return new JsonResponse($this->analytics->summary($campaignId));
    }

    public function campaignRiskReport(Request $request, array $parameters): JsonResponse
    {
        $campaignId = $parameters['id'] ?? '';
        if ($this->storage->getCampaign($campaignId) === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body) || !isset($body['include_zeroes']) || !is_bool($body['include_zeroes'])) {
            return HttpHelper::error('invalid request');
        }

        return new JsonResponse($this->analytics->riskReport($campaignId, $body['include_zeroes']));
    }

    public function createPlayCampaignScene(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $user = $this->auth->requirePlayCampaignOwner($request, $campaign);

        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body)) {
            return HttpHelper::error('invalid json');
        }
        if (!isset($body['id']) || !is_string($body['id']) || $body['id'] === '') {
            return HttpHelper::error('invalid id');
        }
        if (!isset($body['name']) || !is_string($body['name']) || $body['name'] === '') {
            return HttpHelper::error('invalid name');
        }

        if (!$this->storage->createPlayCampaignScene($campaignId, $body['id'], $body['name'])) {
            return new JsonResponse(['error' => 'scene already exists'], 409);
        }

        return new JsonResponse([
            'id' => $body['id'],
            'name' => $body['name'],
            'status' => 'open',
        ], 201);
    }

    public function enterPlayCampaignScene(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $sceneId = $parameters['scene_id'] ?? '';
        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $user = $this->auth->requirePlayCampaignOwner($request, $campaign);

        $scene = $this->storage->getPlayCampaignScene($campaignId, $sceneId);
        if ($scene === null) {
            return new JsonResponse(['error' => 'scene not found'], 404);
        }
        if ($scene['status'] === 'closed') {
            return new JsonResponse(['error' => 'scene is closed'], 409);
        }

        $this->storage->setPlayCampaignCurrentScene($campaignId, $sceneId);
        $this->storage->addPlayCampaignSceneEvent($campaignId, $user['username'], $sceneId);

        return new JsonResponse([
            'current_scene_id' => $sceneId,
            'name' => $scene['name'],
        ]);
    }

    public function closePlayCampaignScene(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $sceneId = $parameters['scene_id'] ?? '';
        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $user = $this->auth->requirePlayCampaignOwner($request, $campaign);

        $scene = $this->storage->getPlayCampaignScene($campaignId, $sceneId);
        if ($scene === null) {
            return new JsonResponse(['error' => 'scene not found'], 404);
        }

        if (!$this->storage->closePlayCampaignScene($campaignId, $sceneId)) {
            return new JsonResponse(['error' => 'scene already closed'], 409);
        }

        return new JsonResponse([
            'id' => $sceneId,
            'status' => 'closed',
        ]);
    }

    public function getPlayCampaignCurrentScene(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        [$user, $isOwner] = $this->auth->requirePlayCampaignMemberOrOwner($request, $campaign);

        $scene = $this->storage->getPlayCampaignCurrentScene($campaignId);
        if ($scene === null) {
            return new JsonResponse(['error' => 'no current scene'], 404);
        }

        return new JsonResponse($scene);
    }

    public function createPlayCampaignLocation(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $user = $this->auth->requirePlayCampaignOwner($request, $campaign);

        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body)) {
            return HttpHelper::error('invalid json');
        }
        if (!isset($body['id']) || !is_string($body['id']) || $body['id'] === '') {
            return HttpHelper::error('invalid id');
        }
        if (!isset($body['name']) || !is_string($body['name']) || $body['name'] === '') {
            return HttpHelper::error('invalid name');
        }

        if (!$this->storage->createPlayCampaignLocation($campaignId, $body['id'], $body['name'])) {
            return new JsonResponse(['error' => 'location already exists'], 409);
        }

        return new JsonResponse([
            'id' => $body['id'],
            'name' => $body['name'],
        ], 201);
    }

    public function createPlayCampaignLocationConnection(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $user = $this->auth->requirePlayCampaignOwner($request, $campaign);

        $fromId = $parameters['from_id'] ?? '';
        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body)) {
            return HttpHelper::error('invalid json');
        }
        if (!isset($body['to_id']) || !is_string($body['to_id']) || $body['to_id'] === '') {
            return HttpHelper::error('invalid to_id');
        }
        if (!isset($body['travel_turns']) || !is_int($body['travel_turns'])) {
            return HttpHelper::error('invalid travel_turns');
        }

        if ($this->storage->getPlayCampaignLocation($campaignId, $fromId) === null) {
            return HttpHelper::error('from location not found');
        }
        if ($this->storage->getPlayCampaignLocation($campaignId, $body['to_id']) === null) {
            return HttpHelper::error('to location not found');
        }

        if (!$this->storage->createPlayCampaignLocationConnection($campaignId, $fromId, $body['to_id'], $body['travel_turns'])) {
            return HttpHelper::error('connection already exists');
        }

        return new JsonResponse([
            'from_id' => $fromId,
            'to_id' => $body['to_id'],
            'travel_turns' => $body['travel_turns'],
        ], 201);
    }

    public function getPlayCampaignTravel(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        [$user, $isOwner] = $this->auth->requirePlayCampaignMemberOrOwner($request, $campaign);

        $locId = $parameters['loc_id'] ?? '';
        if ($this->storage->getPlayCampaignLocation($campaignId, $locId) === null) {
            return new JsonResponse(['error' => 'location not found'], 404);
        }

        return new JsonResponse([
            'destinations' => $this->storage->getPlayCampaignLocationConnections($campaignId, $locId),
        ]);
    }

    public function travelPlayCampaignTurn(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requirePlayerOrConflict($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }
        if (!$this->storage->isPlayCampaignMember($campaignId, $user['username'])) {
            return new JsonResponse(['error' => 'forbidden'], 403);
        }

        if ($campaign['current_actor'] !== $user['username']) {
            return new JsonResponse(['error' => 'conflict'], 409);
        }

        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body) || !isset($body['destination_id']) || !is_string($body['destination_id']) || $body['destination_id'] === '') {
            return new JsonResponse(['error' => 'invalid destination'], 409);
        }
        $destinationId = $body['destination_id'];

        $currentLocationId = $campaign['current_location_id'] ?? null;
        if ($currentLocationId === null) {
            return new JsonResponse(['error' => 'conflict'], 409);
        }

        $connection = $this->storage->getPlayCampaignLocationConnection($campaignId, $currentLocationId, $destinationId);
        if ($connection === null) {
            return new JsonResponse(['error' => 'conflict'], 409);
        }

        $event = $this->storage->addPlayCampaignTravel($campaignId, $user['username'], $destinationId, $connection['travel_turns'], $campaign['owner']);

        return new JsonResponse([
            'sequence' => $event['sequence'],
            'kind' => $event['kind'],
            'actor' => $event['actor'],
            'destination_id' => $event['destination_id'],
            'travel_turns' => $event['travel_turns'],
            'next_actor' => $event['next_actor'],
        ], 201);
    }

    public function restPlayCampaignTurn(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requirePlayerOrConflict($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }
        if (!$this->storage->isPlayCampaignMember($campaignId, $user['username'])) {
            return new JsonResponse(['error' => 'forbidden'], 403);
        }

        if ($campaign['current_actor'] !== $user['username']) {
            return new JsonResponse(['error' => 'conflict'], 409);
        }

        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body) || !isset($body['type']) || !is_string($body['type']) || ($body['type'] !== 'short' && $body['type'] !== 'long')) {
            return HttpHelper::error('invalid type');
        }
        $type = $body['type'];

        $hp = $this->storage->getPlayCampaignMemberHp($campaignId, $user['username']);
        if ($hp === null) {
            return new JsonResponse(['error' => 'forbidden'], 403);
        }

        $event = $this->storage->addPlayCampaignRest($campaignId, $user['username'], $type, $hp['hp_current'], $hp['hp_max'], $campaign['owner']);

        return new JsonResponse([
            'sequence' => $event['sequence'],
            'kind' => $event['kind'],
            'actor' => $event['actor'],
            'type' => $event['type'],
            'hp_current' => $event['hp_current'],
            'hp_max' => $event['hp_max'],
            'next_actor' => $event['next_actor'],
        ], 201);
    }

    public function createPlayCampaignEncounter(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireDm($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $user = $this->auth->requirePlayCampaignOwner($request, $campaign);

        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body)) {
            return HttpHelper::error('invalid json');
        }
        if (!isset($body['id']) || !is_string($body['id']) || $body['id'] === '') {
            return HttpHelper::error('invalid id');
        }
        if (!isset($body['name']) || !is_string($body['name']) || $body['name'] === '') {
            return HttpHelper::error('invalid name');
        }

        if (!$this->storage->createPlayCampaignEncounter($campaignId, $body['id'], $body['name'])) {
            return new JsonResponse(['error' => 'conflict'], 409);
        }

        return new JsonResponse([
            'id' => $body['id'],
            'name' => $body['name'],
            'status' => 'active',
            'combatants' => [],
        ], 201);
    }

    public function addPlayCampaignMonster(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireDm($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $user = $this->auth->requirePlayCampaignOwner($request, $campaign);

        $encounterId = $parameters['enc_id'] ?? '';
        $encounter = $this->storage->getPlayCampaignEncounter($campaignId, $encounterId);
        if ($encounter === null) {
            return new JsonResponse(['error' => 'encounter not found'], 404);
        }

        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body)) {
            return HttpHelper::error('invalid json');
        }
        if (!isset($body['monster_id']) || !is_string($body['monster_id']) || $body['monster_id'] === '') {
            return HttpHelper::error('invalid monster_id');
        }
        if (!isset($body['name']) || !is_string($body['name']) || $body['name'] === '') {
            return HttpHelper::error('invalid name');
        }
        if (!isset($body['hp_max']) || !is_int($body['hp_max'])) {
            return HttpHelper::error('invalid hp_max');
        }
        if (!isset($body['initiative']) || !is_int($body['initiative'])) {
            return HttpHelper::error('invalid initiative');
        }

        $data = [
            'monster_id' => $body['monster_id'],
            'name' => $body['name'],
            'hp_max' => $body['hp_max'],
            'initiative' => $body['initiative'],
        ];

        if (!$this->storage->addPlayCampaignEncounterMonster($campaignId, $encounterId, $data)) {
            return new JsonResponse(['error' => 'monster already exists'], 409);
        }

        return new JsonResponse([
            'monster_id' => $data['monster_id'],
            'name' => $data['name'],
            'hp_max' => $data['hp_max'],
            'hp_current' => $data['hp_max'],
            'initiative' => $data['initiative'],
        ], 201);
    }

    public function removePlayCampaignMonster(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireDm($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $user = $this->auth->requirePlayCampaignOwner($request, $campaign);

        $encounterId = $parameters['enc_id'] ?? '';
        $encounter = $this->storage->getPlayCampaignEncounter($campaignId, $encounterId);
        if ($encounter === null) {
            return new JsonResponse(['error' => 'encounter not found'], 404);
        }

        $monsterId = $parameters['monster_id'] ?? '';
        if (!$this->storage->removePlayCampaignEncounterMonster($campaignId, $encounterId, $monsterId)) {
            return new JsonResponse(['error' => 'monster not found'], 404);
        }

        return new JsonResponse([
            'removed' => $monsterId,
        ], 200);
    }

    public function bindPlayCampaignCombatant(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireDm($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $user = $this->auth->requirePlayCampaignOwner($request, $campaign);

        $encounterId = $parameters['enc_id'] ?? '';
        $encounter = $this->storage->getPlayCampaignEncounter($campaignId, $encounterId);
        if ($encounter === null) {
            return new JsonResponse(['error' => 'encounter not found'], 404);
        }

        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body)) {
            return HttpHelper::error('invalid json');
        }
        if (!isset($body['member']) || !is_string($body['member']) || $body['member'] === '') {
            return HttpHelper::error('invalid member');
        }
        if (!isset($body['initiative']) || !is_int($body['initiative'])) {
            return HttpHelper::error('invalid initiative');
        }

        $member = $this->storage->getPlayCampaignMember($campaignId, $body['member']);
        if ($member === null) {
            return HttpHelper::error('member not found');
        }

        $combatant = [
            'member' => $member['username'],
            'character_id' => $member['character_id'],
            'name' => $member['name'],
            'initiative' => $body['initiative'],
        ];

        if (!$this->storage->addPlayCampaignEncounterCombatant($campaignId, $encounterId, $combatant)) {
            return new JsonResponse(['error' => 'member already bound'], 409);
        }

        return new JsonResponse($combatant, 201);
    }

    public function unbindPlayCampaignCombatant(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireDm($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $user = $this->auth->requirePlayCampaignOwner($request, $campaign);

        $encounterId = $parameters['enc_id'] ?? '';
        $encounter = $this->storage->getPlayCampaignEncounter($campaignId, $encounterId);
        if ($encounter === null) {
            return new JsonResponse(['error' => 'encounter not found'], 404);
        }

        $member = $parameters['member'] ?? '';
        if (!$this->storage->removePlayCampaignEncounterCombatant($campaignId, $encounterId, $member)) {
            return new JsonResponse(['error' => 'combatant not found'], 404);
        }

        return new JsonResponse(['removed' => $member], 200);
    }

    public function getPlayCampaignEncounterTurn(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        [$user, $isOwner] = $this->auth->requirePlayCampaignMemberOrOwner($request, $campaign);

        $encounterId = $parameters['enc_id'] ?? '';
        $turn = $this->storage->getPlayCampaignEncounterTurn($campaignId, $encounterId);
        if ($turn === null) {
            return new JsonResponse(['error' => 'encounter not found'], 404);
        }

        return new JsonResponse([
            'round' => $turn['round'],
            'turn_index' => $turn['turn_index'],
            'active' => $this->mapEncounterActive($turn['active']),
        ]);
    }

    public function addPlayCampaignEncounterCondition(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireDm($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $user = $this->auth->requirePlayCampaignOwner($request, $campaign);

        $encounterId = $parameters['enc_id'] ?? '';
        $encounter = $this->storage->getPlayCampaignEncounter($campaignId, $encounterId);
        if ($encounter === null) {
            return new JsonResponse(['error' => 'encounter not found'], 404);
        }

        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body)) {
            return HttpHelper::error('invalid json');
        }
        if (!isset($body['target']) || !is_string($body['target']) || $body['target'] === '') {
            return HttpHelper::error('invalid target');
        }
        if (!isset($body['condition']) || !is_string($body['condition']) || $body['condition'] === '') {
            return HttpHelper::error('invalid condition');
        }
        if (!isset($body['duration_rounds']) || !is_int($body['duration_rounds']) || $body['duration_rounds'] <= 0) {
            return HttpHelper::error('invalid duration_rounds');
        }

        $target = $body['target'];
        $turn = $this->storage->getPlayCampaignEncounterTurn($campaignId, $encounterId);
        $found = false;
        foreach ($turn['order'] as $combatant) {
            $id = ($combatant['kind'] ?? '') === 'monster' ? ($combatant['monster_id'] ?? '') : ($combatant['member'] ?? '');
            if ($id === $target) {
                $found = true;
                break;
            }
        }
        if (!$found) {
            return HttpHelper::error('invalid target');
        }

        $this->storage->addPlayCampaignEncounterCondition($campaignId, $encounterId, $target, $body['condition'], $body['duration_rounds']);

        return new JsonResponse([
            'target' => $target,
            'conditions' => $this->storage->getPlayCampaignEncounterConditionsForTarget($campaignId, $encounterId, $target),
        ], 201);
    }

    public function getPlayCampaignEncounterStatus(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        [$user, $isOwner] = $this->auth->requirePlayCampaignMemberOrOwner($request, $campaign);

        $encounterId = $parameters['enc_id'] ?? '';
        $encounter = $this->storage->getPlayCampaignEncounter($campaignId, $encounterId);
        if ($encounter === null) {
            return new JsonResponse(['error' => 'encounter not found'], 404);
        }

        $turn = $this->storage->getPlayCampaignEncounterTurn($campaignId, $encounterId);
        if ($turn === null) {
            return new JsonResponse(['error' => 'encounter not found'], 404);
        }

        $order = [];
        foreach ($turn['order'] as $combatant) {
            $order[] = $this->mapEncounterCombatant($combatant);
        }

        $savedConditions = $this->storage->getPlayCampaignEncounterConditionsMap($campaignId, $encounterId);
        $conditions = [];
        foreach ($turn['order'] as $combatant) {
            $id = ($combatant['kind'] ?? '') === 'monster' ? ($combatant['monster_id'] ?? '') : ($combatant['member'] ?? '');
            $conditions[$id] = $savedConditions[$id] ?? [];
        }

        return new JsonResponse([
            'id' => $encounterId,
            'name' => $encounter['name'],
            'status' => $encounter['status'],
            'round' => $turn['round'],
            'turn_index' => $turn['turn_index'],
            'active' => $this->mapEncounterCombatant($turn['active']),
            'order' => $order,
            'conditions' => (object) $conditions,
        ]);
    }

    public function advancePlayCampaignEncounterTurn(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        [$user, $isOwner] = $this->auth->requirePlayCampaignMemberOrOwner($request, $campaign);

        $encounterId = $parameters['enc_id'] ?? '';
        $turn = $this->storage->getPlayCampaignEncounterTurn($campaignId, $encounterId);
        if ($turn === null) {
            return new JsonResponse(['error' => 'encounter not found'], 404);
        }

        $canAdvance = $isOwner;
        if (!$canAdvance && $turn['active'] !== null && $turn['active']['kind'] === 'member' && $turn['active']['member'] === $user['username']) {
            $canAdvance = true;
        }
        if (!$canAdvance) {
            return new JsonResponse(['error' => 'conflict'], 409);
        }

        $newTurn = $this->storage->advancePlayCampaignEncounterTurn($campaignId, $encounterId);
        if ($newTurn === null) {
            return new JsonResponse(['error' => 'encounter not found'], 404);
        }

        return new JsonResponse([
            'round' => $newTurn['round'],
            'turn_index' => $newTurn['turn_index'],
            'active' => $this->mapEncounterActive($newTurn['active']),
        ]);
    }

    public function submitPlayCampaignEncounterAction(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        [$user, $isOwner] = $this->auth->requirePlayCampaignMemberOrOwner($request, $campaign);

        $encounterId = $parameters['enc_id'] ?? '';
        $encounter = $this->storage->getPlayCampaignEncounter($campaignId, $encounterId);
        if ($encounter === null) {
            return new JsonResponse(['error' => 'encounter not found'], 404);
        }

        $turn = $this->storage->getPlayCampaignEncounterTurn($campaignId, $encounterId);
        $active = $turn['active'] ?? null;
        if ($active === null || ($active['kind'] ?? null) !== 'member' || ($active['member'] ?? null) !== $user['username']) {
            return new JsonResponse(['error' => 'conflict'], 409);
        }

        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body)) {
            return HttpHelper::error('invalid json');
        }
        if (!isset($body['type']) || !is_string($body['type']) || !in_array($body['type'], ['attack', 'help', 'dodge', 'ready'], true)) {
            return HttpHelper::error('invalid type');
        }
        if (!isset($body['target']) || !is_string($body['target']) || $body['target'] === '') {
            return HttpHelper::error('invalid target');
        }
        if (!isset($body['text']) || !is_string($body['text']) || $body['text'] === '') {
            return HttpHelper::error('invalid text');
        }

        $event = $this->storage->addPlayCampaignEncounterAction($campaignId, $encounterId, $user['username'], $body['type'], $body['target'], $body['text']);

        return new JsonResponse([
            'sequence' => $event['sequence'],
            'kind' => $event['kind'],
            'actor' => $event['actor'],
            'type' => $event['type'],
            'target' => $event['target'],
            'text' => $event['text'],
        ], 201);
    }

    public function delayPlayCampaignEncounterTurn(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        [$user, $isOwner] = $this->auth->requirePlayCampaignMemberOrOwner($request, $campaign);

        $encounterId = $parameters['enc_id'] ?? '';
        $turn = $this->storage->getPlayCampaignEncounterTurn($campaignId, $encounterId);
        if ($turn === null) {
            return new JsonResponse(['error' => 'encounter not found'], 404);
        }

        $active = $turn['active'] ?? null;
        $canDelay = $isOwner;
        if (!$canDelay && $active !== null && $active['kind'] === 'member' && ($active['member'] ?? null) === $user['username']) {
            $canDelay = true;
        }
        if (!$canDelay) {
            return new JsonResponse(['error' => 'conflict'], 409);
        }

        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body) || !isset($body['new_index']) || !is_int($body['new_index'])) {
            return HttpHelper::error('invalid index');
        }

        $result = $this->storage->delayPlayCampaignEncounterTurn($campaignId, $encounterId, $body['new_index']);
        if ($result === null) {
            return new JsonResponse(['error' => 'encounter not found'], 404);
        }
        if (isset($result['error'])) {
            return HttpHelper::error('invalid index');
        }

        $order = [];
        foreach ($result['order'] as $combatant) {
            $order[] = $this->mapEncounterCombatant($combatant);
        }

        return new JsonResponse(['order' => $order]);
    }

    public function readyPlayCampaignEncounterTurn(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        [$user, $isOwner] = $this->auth->requirePlayCampaignMemberOrOwner($request, $campaign);

        $encounterId = $parameters['enc_id'] ?? '';
        $turn = $this->storage->getPlayCampaignEncounterTurn($campaignId, $encounterId);
        if ($turn === null) {
            return new JsonResponse(['error' => 'encounter not found'], 404);
        }

        $active = $turn['active'] ?? null;
        if ($active === null || $active['kind'] !== 'member' || ($active['member'] ?? null) !== $user['username']) {
            return new JsonResponse(['error' => 'conflict'], 409);
        }

        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body) || !isset($body['trigger']) || !is_string($body['trigger']) || $body['trigger'] === '') {
            return HttpHelper::error('invalid trigger');
        }

        return new JsonResponse([
            'actor' => $user['username'],
            'trigger' => $body['trigger'],
        ], 201);
    }

    public function damagePlayCampaignEncounter(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireDm($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $user = $this->auth->requirePlayCampaignOwner($request, $campaign);

        $encounterId = $parameters['enc_id'] ?? '';
        $encounter = $this->storage->getPlayCampaignEncounter($campaignId, $encounterId);
        if ($encounter === null) {
            return new JsonResponse(['error' => 'encounter not found'], 404);
        }

        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body)) {
            return HttpHelper::error('invalid json');
        }
        if (!isset($body['target']) || !is_string($body['target']) || $body['target'] === '') {
            return HttpHelper::error('invalid target');
        }
        if (!isset($body['amount']) || !is_int($body['amount']) || $body['amount'] <= 0) {
            return HttpHelper::error('invalid amount');
        }

        $result = $this->storage->damagePlayCampaignEncounterCombatant($campaignId, $encounterId, $body['target'], $body['amount']);
        if ($result === null) {
            return new JsonResponse(['error' => 'combatant not found'], 404);
        }

        return new JsonResponse($result, 200);
    }

    public function healPlayCampaignEncounter(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireDm($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $user = $this->auth->requirePlayCampaignOwner($request, $campaign);

        $encounterId = $parameters['enc_id'] ?? '';
        $encounter = $this->storage->getPlayCampaignEncounter($campaignId, $encounterId);
        if ($encounter === null) {
            return new JsonResponse(['error' => 'encounter not found'], 404);
        }

        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body)) {
            return HttpHelper::error('invalid json');
        }
        if (!isset($body['target']) || !is_string($body['target']) || $body['target'] === '') {
            return HttpHelper::error('invalid target');
        }
        if (!isset($body['amount']) || !is_int($body['amount']) || $body['amount'] <= 0) {
            return HttpHelper::error('invalid amount');
        }

        $result = $this->storage->healPlayCampaignEncounterCombatant($campaignId, $encounterId, $body['target'], $body['amount']);
        if ($result === null) {
            return new JsonResponse(['error' => 'combatant not found'], 404);
        }

        return new JsonResponse($result, 200);
    }

    public function awardPlayCampaignEncounterRewards(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireDm($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $user = $this->auth->requirePlayCampaignOwner($request, $campaign);

        $encounterId = $parameters['enc_id'] ?? '';
        $encounter = $this->storage->getPlayCampaignEncounter($campaignId, $encounterId);
        if ($encounter === null) {
            return new JsonResponse(['error' => 'encounter not found'], 404);
        }

        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body)) {
            return HttpHelper::error('invalid json');
        }
        if (!isset($body['xp']) || !is_int($body['xp'])) {
            return HttpHelper::error('invalid xp');
        }
        $xp = $body['xp'];
        if ($xp < 0) {
            return HttpHelper::error('invalid xp');
        }

        $loot = $body['loot'] ?? [];
        if (!is_array($loot)) {
            return HttpHelper::error('invalid loot');
        }
        $normalizedLoot = [];
        foreach ($loot as $entry) {
            if (!is_array($entry) || !isset($entry['slug']) || !is_string($entry['slug']) || $entry['slug'] === '' || !isset($entry['quantity']) || !is_int($entry['quantity']) || $entry['quantity'] <= 0) {
                return HttpHelper::error('invalid loot');
            }
            $normalizedLoot[] = [
                'slug' => $entry['slug'],
                'quantity' => $entry['quantity'],
            ];
        }

        if (!$this->storage->awardPlayCampaignEncounterRewards($campaignId, $encounterId, $xp, $normalizedLoot)) {
            return new JsonResponse(['error' => 'rewards already awarded'], 409);
        }

        return new JsonResponse([
            'id' => $encounterId,
            'xp' => $xp,
            'loot' => $normalizedLoot,
        ], 200);
    }

    public function closePlayCampaignEncounter(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireDm($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $user = $this->auth->requirePlayCampaignOwner($request, $campaign);

        $encounterId = $parameters['enc_id'] ?? '';
        $encounter = $this->storage->getPlayCampaignEncounter($campaignId, $encounterId);
        if ($encounter === null) {
            return new JsonResponse(['error' => 'encounter not found'], 404);
        }
        if ($encounter['status'] !== 'active') {
            return new JsonResponse(['error' => 'conflict'], 409);
        }

        if (!$this->storage->closePlayCampaignEncounter($campaignId, $encounterId)) {
            return new JsonResponse(['error' => 'conflict'], 409);
        }

        $encounter = $this->storage->getPlayCampaignEncounter($campaignId, $encounterId);

        return new JsonResponse([
            'id' => $encounter['id'],
            'name' => $encounter['name'],
            'status' => $encounter['status'],
            'combatants' => $encounter['combatants'],
            'xp_awarded' => $encounter['xp_awarded'],
            'loot' => $encounter['loot'],
        ], 200);
    }

    public function endPlayCampaignEncounter(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireDm($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $user = $this->auth->requirePlayCampaignOwner($request, $campaign);

        $encounterId = $parameters['enc_id'] ?? '';

        $encounter = $this->storage->getPlayCampaignEncounter($campaignId, $encounterId);
        if ($encounter === null) {
            return new JsonResponse(['error' => 'conflict'], 409);
        }

        if ($encounter['status'] === 'active') {
            $restoredActor = $this->storage->endPlayCampaignEncounter($campaignId, $encounterId);
            if ($restoredActor === null) {
                return new JsonResponse(['error' => 'conflict'], 409);
            }
        }

        $campaign = $this->storage->getPlayCampaign($campaignId);

        // If combat ended on a player's exploration turn, the turn passes to
        // the next actor in the deterministic queue so the DM can continue.
        if ($campaign['current_actor'] !== $campaign['owner']) {
            $members = $this->storage->getPlayCampaignMembers($campaignId);
            $queue = [];
            foreach ($members as $member) {
                $queue[] = $member['username'];
                $queue[] = $campaign['owner'];
            }
            $index = array_search($campaign['current_actor'], $queue, true);
            $nextIndex = $index === false || $index === count($queue) - 1 ? 0 : $index + 1;
            $this->storage->setPlayCampaignCurrentActor($campaignId, $queue[$nextIndex]);
            $campaign = $this->storage->getPlayCampaign($campaignId);
        }

        return new JsonResponse([
            'campaign_id' => $campaignId,
            'status' => 'active',
            'phase' => 'exploration',
            'current_actor' => $campaign['current_actor'] ?? $campaign['owner'],
        ], 200);
    }

    public function damagePlayCampaignCharacter(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $user = $this->auth->requirePlayCampaignOwner($request, $campaign);

        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body)) {
            return HttpHelper::error('invalid json');
        }
        if (!isset($body['amount']) || !is_int($body['amount']) || $body['amount'] <= 0) {
            return HttpHelper::error('invalid amount');
        }

        $characterId = $parameters['char_id'] ?? '';
        $result = $this->storage->damagePlayCampaignCharacter($campaignId, $characterId, $body['amount']);
        if ($result === null) {
            return new JsonResponse(['error' => 'character not found'], 404);
        }

        return new JsonResponse($result, 200);
    }

    public function recordDeathSave(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }
        $characterId = $parameters['char_id'] ?? '';
        $member = $this->storage->getPlayCampaignMemberByCharacterId($campaignId, $characterId);
        if ($member === null) {
            return new JsonResponse(['error' => 'character not found'], 404);
        }

        if ($member['username'] !== $user['username']) {
            return new JsonResponse(['error' => 'forbidden'], 403);
        }

        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body)) {
            return HttpHelper::error('invalid json');
        }
        if (!isset($body['outcome']) || !is_string($body['outcome']) || ($body['outcome'] !== 'success' && $body['outcome'] !== 'failure')) {
            return HttpHelper::error('invalid outcome');
        }

        if ($member['status'] !== 'unconscious') {
            return new JsonResponse(['error' => 'character is not unconscious'], 409);
        }

        $result = $this->storage->recordDeathSave($campaignId, $characterId, $body['outcome']);
        if ($result === null) {
            return new JsonResponse(['error' => 'character not found'], 404);
        }

        return new JsonResponse($result, 201);
    }

    public function getPlayCampaignCharacterStatus(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        [$user, $isOwner] = $this->auth->requirePlayCampaignMemberOrOwner($request, $campaign);

        $characterId = $parameters['char_id'] ?? '';
        $status = $this->storage->getPlayCampaignCharacterStatus($campaignId, $characterId);
        if ($status === null) {
            return new JsonResponse(['error' => 'character not found'], 404);
        }

        return new JsonResponse($status);
    }

    public function getPlayCampaignCharacterOwner(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        [$user, $isOwner] = $this->auth->requirePlayCampaignMemberOrOwner($request, $campaign);

        $characterId = $parameters['char_id'] ?? '';
        $ownerData = $this->storage->getPlayCampaignCharacterOwner($campaignId, $characterId);
        if ($ownerData === null) {
            return new JsonResponse(['error' => 'character not found'], 404);
        }

        return new JsonResponse([
            'character_id' => $characterId,
            'owner' => $ownerData['owner'],
        ]);
    }

    public function claimPlayCampaignCharacter(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requirePlayer($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }
        if (!$this->storage->isPlayCampaignMember($campaignId, $user['username'])) {
            return new JsonResponse(['error' => 'forbidden'], 403);
        }

        $characterId = $parameters['char_id'] ?? '';
        $ownerData = $this->storage->getPlayCampaignCharacterOwner($campaignId, $characterId);
        if ($ownerData === null) {
            return new JsonResponse(['error' => 'character not found'], 404);
        }

        if ($ownerData['owner'] !== null && $ownerData['owner'] !== $user['username']) {
            return new JsonResponse(['error' => 'character already claimed'], 409);
        }

        if (!$this->storage->claimPlayCampaignCharacter($campaignId, $characterId, $user['username'])) {
            return new JsonResponse(['error' => 'character already claimed'], 409);
        }

        return new JsonResponse([
            'character_id' => $characterId,
            'owner' => $user['username'],
        ], 201);
    }

    public function transferPlayCampaignCharacter(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }
        $characterId = $parameters['char_id'] ?? '';
        $ownerData = $this->storage->getPlayCampaignCharacterOwner($campaignId, $characterId);
        if ($ownerData === null) {
            return new JsonResponse(['error' => 'character not found'], 404);
        }

        if ($ownerData['owner'] !== $user['username']) {
            return new JsonResponse(['error' => 'forbidden'], 403);
        }

        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body) || !isset($body['new_owner']) || !is_string($body['new_owner']) || $body['new_owner'] === '') {
            return HttpHelper::error('invalid new_owner');
        }
        $newOwner = $body['new_owner'];

        if (!$this->storage->isPlayCampaignMember($campaignId, $newOwner)) {
            return HttpHelper::error('new owner is not a member');
        }

        if (!$this->storage->transferPlayCampaignCharacter($campaignId, $characterId, $newOwner)) {
            return HttpHelper::error('transfer failed');
        }

        return new JsonResponse([
            'character_id' => $characterId,
            'owner' => $newOwner,
        ]);
    }

    public function buildPlayCampaignCharacter(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }
        $characterId = $parameters['char_id'] ?? '';
        $ownerData = $this->storage->getPlayCampaignCharacterOwner($campaignId, $characterId);
        if ($ownerData === null) {
            return new JsonResponse(['error' => 'character not found'], 404);
        }

        if ($ownerData['owner'] !== $user['username']) {
            return new JsonResponse(['error' => 'forbidden'], 403);
        }

        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body)) {
            return HttpHelper::error('invalid json');
        }

        if (!isset($body['race']) || !is_string($body['race']) || !in_array($body['race'], CharacterRules::RACES, true)) {
            return HttpHelper::error('invalid race');
        }
        $race = $body['race'];

        if (!isset($body['class']) || !is_string($body['class']) || !in_array($body['class'], CharacterRules::CLASSES, true)) {
            return HttpHelper::error('invalid class');
        }
        $class = $body['class'];

        if (!isset($body['background']) || !is_string($body['background']) || !in_array($body['background'], CharacterRules::BACKGROUNDS, true)) {
            return HttpHelper::error('invalid background');
        }
        $background = $body['background'];

        $abilities = $body['abilities'] ?? null;
        if (!is_array($abilities)) {
            return HttpHelper::error('invalid abilities');
        }
        foreach (CharacterRules::ABILITY_NAMES as $name) {
            if (!isset($abilities[$name]) || !is_int($abilities[$name]) || $abilities[$name] < 1 || $abilities[$name] > 30) {
                return HttpHelper::error('invalid abilities');
            }
        }

        $level = 1;
        $conModifier = CharacterRules::modifier($abilities['con']);
        $hpMax = CharacterRules::hitDieMax($class) + $conModifier;
        if ($hpMax < 1) {
            $hpMax = 1;
        }
        $proficiencyBonus = CharacterRules::proficiencyBonus($level);

        if (!$this->storage->buildPlayCampaignCharacter($campaignId, $characterId, $race, $class, $background, $abilities, $hpMax, $level)) {
            return new JsonResponse(['error' => 'character not found'], 404);
        }

        return new JsonResponse([
            'character_id' => $characterId,
            'race' => $race,
            'class' => $class,
            'background' => $background,
            'level' => $level,
            'hp_max' => $hpMax,
            'proficiency_bonus' => $proficiencyBonus,
        ], 200);
    }

    public function levelUpPlayCampaignCharacter(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }
        $characterId = $parameters['char_id'] ?? '';
        $character = $this->storage->getPlayCampaignCharacterLevelData($campaignId, $characterId);
        if ($character === null) {
            return new JsonResponse(['error' => 'character not found'], 404);
        }

        if ($character['owner'] !== $user['username']) {
            return new JsonResponse(['error' => 'forbidden'], 403);
        }

        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body) || !isset($body['level']) || !is_int($body['level'])) {
            return HttpHelper::error('invalid level');
        }

        $requestedLevel = $body['level'];
        if ($requestedLevel !== $character['level'] + 1) {
            return HttpHelper::error('invalid level');
        }

        $abilities = json_decode($character['abilities_json'], true, 512, JSON_THROW_ON_ERROR);
        if (!is_array($abilities)) {
            $abilities = [];
        }
        $conModifier = CharacterRules::modifier((int) ($abilities['con'] ?? 10));
        $newHpMax = CharacterRules::levelUpHp($character['hp_max'], $character['class'], $conModifier, $character['level'], $requestedLevel);
        $hpGain = $newHpMax - $character['hp_max'];
        $newHpCurrent = min($character['hp_current'] + $hpGain, $newHpMax);

        $updated = $this->storage->levelUpPlayCampaignCharacter($campaignId, $characterId, $requestedLevel, $newHpMax, $newHpCurrent);
        if ($updated === null) {
            return new JsonResponse(['error' => 'character not found'], 404);
        }

        return new JsonResponse([
            'character_id' => $characterId,
            'level' => $requestedLevel,
            'hp_max' => $newHpMax,
            'hit_dice' => CharacterRules::hitDieString($character['class']),
            'proficiency_bonus' => CharacterRules::proficiencyBonus($requestedLevel),
        ]);
    }

    public function playCampaignCharacterSkillCheck(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }
        $characterId = $parameters['char_id'] ?? '';
        $character = $this->storage->getPlayCampaignCharacterSkillData($campaignId, $characterId);
        if ($character === null) {
            return new JsonResponse(['error' => 'character not found'], 404);
        }

        if ($character['owner'] !== $user['username']) {
            return new JsonResponse(['error' => 'forbidden'], 403);
        }

        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body)) {
            return HttpHelper::error('invalid json');
        }
        if (!isset($body['skill']) || !is_string($body['skill']) || !in_array($body['skill'], CharacterRules::SKILL_NAMES, true)) {
            return HttpHelper::error('invalid skill');
        }
        if (!isset($body['ability']) || !is_string($body['ability']) || !in_array($body['ability'], CharacterRules::ABILITY_NAMES, true)) {
            return HttpHelper::error('invalid ability');
        }
        if (!isset($body['proficient']) || !is_bool($body['proficient'])) {
            return HttpHelper::error('invalid proficient');
        }
        if (!isset($body['roll']) || !is_int($body['roll'])) {
            return HttpHelper::error('invalid roll');
        }

        $abilityScore = (int) ($character['abilities'][$body['ability']] ?? 10);
        $abilityModifier = CharacterRules::modifier($abilityScore);
        $proficiencyBonus = $body['proficient'] ? CharacterRules::proficiencyBonus($character['level']) : 0;
        $modifier = $abilityModifier + $proficiencyBonus;
        $total = $body['roll'] + $modifier;

        return new JsonResponse([
            'character_id' => $characterId,
            'skill' => $body['skill'],
            'ability' => $body['ability'],
            'modifier' => $modifier,
            'total' => $total,
        ]);
    }

    public function addCharacterSpell(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $characterId = $parameters['char_id'] ?? '';
        $character = $this->storage->getPlayCampaignMemberByCharacterId($campaignId, $characterId);
        if ($character === null) {
            return new JsonResponse(['error' => 'character not found'], 404);
        }

        if ($character['owner'] !== $user['username']) {
            return new JsonResponse(['error' => 'forbidden'], 403);
        }

        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body)) {
            return HttpHelper::error('invalid json');
        }
        if (!isset($body['spell_id']) || !is_string($body['spell_id']) || $body['spell_id'] === '') {
            return HttpHelper::error('invalid spell_id');
        }
        if (!isset($body['name']) || !is_string($body['name']) || $body['name'] === '') {
            return HttpHelper::error('invalid name');
        }
        if (!isset($body['level']) || !is_int($body['level'])) {
            return HttpHelper::error('invalid level');
        }

        $spellId = $body['spell_id'];
        $name = $body['name'];
        $level = $body['level'];

        if (!SpellRules::canLearn($character['class'], $spellId)) {
            return HttpHelper::error('invalid class/spell combination');
        }

        if (!$this->storage->addCharacterSpell($campaignId, $characterId, $spellId, $name, $level)) {
            return new JsonResponse(['error' => 'spell already known'], 409);
        }

        return new JsonResponse([
            'spell_id' => $spellId,
            'name' => $name,
            'level' => $level,
        ], 201);
    }

    public function getCharacterSpellbook(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $this->auth->requirePlayCampaignMemberOrOwner($request, $campaign);

        $characterId = $parameters['char_id'] ?? '';
        $character = $this->storage->getPlayCampaignMemberByCharacterId($campaignId, $characterId);
        if ($character === null) {
            return new JsonResponse(['error' => 'character not found'], 404);
        }

        return new JsonResponse([
            'spells' => $this->storage->getCharacterSpells($campaignId, $characterId),
        ]);
    }

    public function updateCharacterPreparedSpells(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $characterId = $parameters['char_id'] ?? '';
        $character = $this->storage->getPlayCampaignMemberByCharacterId($campaignId, $characterId);
        if ($character === null) {
            return new JsonResponse(['error' => 'character not found'], 404);
        }

        if ($character['owner'] !== $user['username']) {
            return new JsonResponse(['error' => 'forbidden'], 403);
        }

        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body)) {
            return HttpHelper::error('invalid json');
        }
        if (!isset($body['spell_ids']) || !is_array($body['spell_ids'])) {
            return HttpHelper::error('invalid spell_ids');
        }

        $maxPrepared = SpellRules::maxPreparedSpells($character['class'], $character['level']);
        if ($maxPrepared === 0) {
            return HttpHelper::error('character cannot prepare spells');
        }

        $requestedSpellIds = [];
        $seen = [];
        foreach ($body['spell_ids'] as $spellId) {
            if (!is_string($spellId) || $spellId === '') {
                return HttpHelper::error('invalid spell_ids');
            }
            if (isset($seen[$spellId])) {
                continue;
            }
            $seen[$spellId] = true;
            $requestedSpellIds[] = $spellId;
        }

        if (count($requestedSpellIds) > $maxPrepared) {
            return HttpHelper::error('too many prepared spells');
        }

        $knownSpellIds = array_map(
            static fn (array $spell): string => $spell['spell_id'],
            $this->storage->getCharacterSpells($campaignId, $characterId),
        );
        foreach ($requestedSpellIds as $spellId) {
            if (!in_array($spellId, $knownSpellIds, true)) {
                return HttpHelper::error('spell not known');
            }
        }

        $this->storage->setCharacterPreparedSpells($campaignId, $characterId, $requestedSpellIds);

        return new JsonResponse([
            'character_id' => $characterId,
            'prepared_spells' => $requestedSpellIds,
            'max_prepared' => $maxPrepared,
        ]);
    }

    public function getCharacterPreparedSpells(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $this->auth->requirePlayCampaignMemberOrOwner($request, $campaign);

        $characterId = $parameters['char_id'] ?? '';
        $character = $this->storage->getPlayCampaignMemberByCharacterId($campaignId, $characterId);
        if ($character === null) {
            return new JsonResponse(['error' => 'character not found'], 404);
        }

        $maxPrepared = SpellRules::maxPreparedSpells($character['class'], $character['level']);

        return new JsonResponse([
            'character_id' => $characterId,
            'prepared_spells' => $this->storage->getCharacterPreparedSpells($campaignId, $characterId),
            'max_prepared' => $maxPrepared,
        ]);
    }

    public function castCharacterSpell(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $this->auth->requirePlayCampaignMemberOrOwner($request, $campaign);

        $characterId = $parameters['character_id'] ?? '';
        $character = $this->storage->getPlayCampaignMemberByCharacterId($campaignId, $characterId);
        if ($character === null) {
            return new JsonResponse(['error' => 'character not found'], 404);
        }

        if ($character['owner'] !== $user['username']) {
            return new JsonResponse(['error' => 'forbidden'], 403);
        }

        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body)) {
            return HttpHelper::error('invalid json');
        }
        if (!isset($body['spell_id']) || !is_string($body['spell_id']) || $body['spell_id'] === '') {
            return HttpHelper::error('invalid spell_id');
        }
        if (!isset($body['target']) || !is_string($body['target']) || $body['target'] === '') {
            return HttpHelper::error('invalid target');
        }

        $spellId = $body['spell_id'];
        $target = $body['target'];

        if (!SpellRules::isSpellcaster($character['class'])) {
            return HttpHelper::error('character is not a spellcaster');
        }

        $prepared = $this->storage->getCharacterPreparedSpells($campaignId, $characterId);
        if (!in_array($spellId, $prepared, true)) {
            return HttpHelper::error('spell not prepared');
        }

        $known = $this->storage->getCharacterSpells($campaignId, $characterId);
        $slotLevel = null;
        foreach ($known as $spell) {
            if ($spell['spell_id'] === $spellId) {
                $slotLevel = $spell['level'];
                break;
            }
        }
        if ($slotLevel === null) {
            return HttpHelper::error('spell not known');
        }

        if ($slotLevel === 0) {
            $cast = $this->storage->recordCharacterSpellCast($campaignId, $characterId, $spellId, $target, 0, 0);

            return new JsonResponse($cast, 201);
        }

        $slots = $this->storage->getCharacterSpellSlots($campaignId, $characterId);
        $remaining = (int) ($slots[$slotLevel] ?? 0);
        if ($remaining <= 0) {
            return new JsonResponse(['error' => 'no remaining spell slots'], 409);
        }

        $newRemaining = $this->storage->consumeCharacterSpellSlot($campaignId, $characterId, $slotLevel);
        if ($newRemaining === null) {
            return new JsonResponse(['error' => 'no remaining spell slots'], 409);
        }

        $cast = $this->storage->recordCharacterSpellCast($campaignId, $characterId, $spellId, $target, $slotLevel, $newRemaining);

        return new JsonResponse($cast, 201);
    }

    public function getCharacterCasts(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $this->auth->requirePlayCampaignMemberOrOwner($request, $campaign);

        $characterId = $parameters['character_id'] ?? '';
        $character = $this->storage->getPlayCampaignMemberByCharacterId($campaignId, $characterId);
        if ($character === null) {
            return new JsonResponse(['error' => 'character not found'], 404);
        }

        return new JsonResponse([
            'casts' => $this->storage->getCharacterSpellCasts($campaignId, $characterId),
        ]);
    }

    public function setCharacterConcentration(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $characterId = $parameters['character_id'] ?? '';
        $character = $this->storage->getPlayCampaignMemberByCharacterId($campaignId, $characterId);
        if ($character === null) {
            return new JsonResponse(['error' => 'character not found'], 404);
        }

        if ($character['owner'] !== $user['username']) {
            return new JsonResponse(['error' => 'forbidden'], 403);
        }

        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body)) {
            return HttpHelper::error('invalid json');
        }
        if (!isset($body['spell_id']) || !is_string($body['spell_id']) || $body['spell_id'] === '') {
            return HttpHelper::error('invalid spell_id');
        }
        if (!isset($body['target']) || !is_string($body['target']) || $body['target'] === '') {
            return HttpHelper::error('invalid target');
        }
        if (!isset($body['duration_turns']) || !is_int($body['duration_turns'])) {
            return HttpHelper::error('invalid duration_turns');
        }

        $spellId = $body['spell_id'];
        $target = $body['target'];
        $durationTurns = $body['duration_turns'];

        if (!SpellRules::isSpellcaster($character['class'])) {
            return HttpHelper::error('character is not a spellcaster');
        }

        $known = $this->storage->getCharacterSpells($campaignId, $characterId);
        $knownSpellIds = array_map(static fn (array $spell): string => $spell['spell_id'], $known);
        if (!in_array($spellId, $knownSpellIds, true)) {
            return HttpHelper::error('spell is unknown');
        }

        $prepared = $this->storage->getCharacterPreparedSpells($campaignId, $characterId);
        if (!in_array($spellId, $prepared, true)) {
            return HttpHelper::error('spell is not prepared');
        }

        if ($durationTurns < 1) {
            return HttpHelper::error('duration_turns must be positive');
        }

        $this->storage->setCharacterConcentration($campaignId, $characterId, $spellId, $target, $durationTurns);

        return new JsonResponse([
            'character_id' => $characterId,
            'concentration' => [
                'spell_id' => $spellId,
                'target' => $target,
                'remaining_turns' => $durationTurns,
            ],
        ]);
    }

    public function getCharacterConcentration(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $this->auth->requirePlayCampaignMemberOrOwner($request, $campaign);

        $characterId = $parameters['character_id'] ?? '';
        $character = $this->storage->getPlayCampaignMemberByCharacterId($campaignId, $characterId);
        if ($character === null) {
            return new JsonResponse(['error' => 'character not found'], 404);
        }

        $concentration = $this->storage->getCharacterConcentration($campaignId, $characterId);

        return new JsonResponse([
            'character_id' => $characterId,
            'concentration' => $concentration,
        ]);
    }

    public function advanceCharacterConcentrationTurn(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $this->auth->requirePlayCampaignMemberOrOwner($request, $campaign);

        $characterId = $parameters['character_id'] ?? '';
        $character = $this->storage->getPlayCampaignMemberByCharacterId($campaignId, $characterId);
        if ($character === null) {
            return new JsonResponse(['error' => 'character not found'], 404);
        }

        $concentration = $this->storage->advanceCharacterConcentration($campaignId, $characterId);

        return new JsonResponse([
            'character_id' => $characterId,
            'concentration' => $concentration,
        ]);
    }

    public function clearCharacterConcentration(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $characterId = $parameters['character_id'] ?? '';
        $character = $this->storage->getPlayCampaignMemberByCharacterId($campaignId, $characterId);
        if ($character === null) {
            return new JsonResponse(['error' => 'character not found'], 404);
        }

        if ($character['owner'] !== $user['username']) {
            return new JsonResponse(['error' => 'forbidden'], 403);
        }

        $this->storage->clearCharacterConcentration($campaignId, $characterId);

        return new JsonResponse([
            'character_id' => $characterId,
            'concentration' => null,
        ]);
    }

    public function addPlayCampaignCharacterInventoryItem(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $characterId = $parameters['character_id'] ?? '';
        $character = $this->storage->getPlayCampaignMemberByCharacterId($campaignId, $characterId);
        if ($character === null) {
            return new JsonResponse(['error' => 'character not found'], 404);
        }

        if ($character['owner'] !== $user['username']) {
            return new JsonResponse(['error' => 'forbidden'], 403);
        }

        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body)) {
            return HttpHelper::error('invalid json');
        }
        if (!isset($body['item_id']) || !is_string($body['item_id']) || !in_array($body['item_id'], self::PLAY_CAMPAIGN_INVENTORY_ITEMS, true)) {
            return HttpHelper::error('invalid item_id');
        }
        if (!isset($body['quantity']) || !is_int($body['quantity']) || $body['quantity'] <= 0) {
            return HttpHelper::error('invalid quantity');
        }

        $itemId = $body['item_id'];
        $quantity = $body['quantity'];
        $total = $this->storage->addPlayCampaignCharacterInventoryItem($campaignId, $characterId, $itemId, $quantity);

        return new JsonResponse([
            'character_id' => $characterId,
            'item_id' => $itemId,
            'quantity' => $quantity,
            'total_quantity' => $total,
        ], 201);
    }

    public function getPlayCampaignCharacterInventoryItems(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $this->auth->requirePlayCampaignMemberOrOwner($request, $campaign);

        $characterId = $parameters['character_id'] ?? '';
        $character = $this->storage->getPlayCampaignMemberByCharacterId($campaignId, $characterId);
        if ($character === null) {
            return new JsonResponse(['error' => 'character not found'], 404);
        }

        return new JsonResponse([
            'character_id' => $characterId,
            'items' => $this->storage->getPlayCampaignCharacterInventoryItems($campaignId, $characterId),
        ]);
    }

    public function removePlayCampaignCharacterInventoryItem(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $characterId = $parameters['character_id'] ?? '';
        $character = $this->storage->getPlayCampaignMemberByCharacterId($campaignId, $characterId);
        if ($character === null) {
            return new JsonResponse(['error' => 'character not found'], 404);
        }

        if ($character['owner'] !== $user['username']) {
            return new JsonResponse(['error' => 'forbidden'], 403);
        }

        $itemId = $parameters['item_id'] ?? '';
        if (!in_array($itemId, self::PLAY_CAMPAIGN_INVENTORY_ITEMS, true)) {
            return HttpHelper::error('invalid item_id');
        }

        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body)) {
            return HttpHelper::error('invalid json');
        }
        if (!isset($body['quantity']) || !is_int($body['quantity']) || $body['quantity'] <= 0) {
            return HttpHelper::error('invalid quantity');
        }
        $quantity = $body['quantity'];

        $total = $this->storage->removePlayCampaignCharacterInventoryItem($campaignId, $characterId, $itemId, $quantity);
        if ($total === null) {
            return new JsonResponse(['error' => 'insufficient quantity'], 409);
        }

        return new JsonResponse([
            'character_id' => $characterId,
            'item_id' => $itemId,
            'quantity' => $quantity,
            'total_quantity' => $total,
        ], 200);
    }

    public function equipPlayCampaignCharacterItem(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $characterId = $parameters['character_id'] ?? '';
        $character = $this->storage->getPlayCampaignMemberByCharacterId($campaignId, $characterId);
        if ($character === null) {
            return new JsonResponse(['error' => 'character not found'], 404);
        }

        if ($character['owner'] !== $user['username']) {
            return new JsonResponse(['error' => 'forbidden'], 403);
        }

        $slot = $parameters['slot'] ?? '';
        if (!in_array($slot, ['armor', 'accessory'], true)) {
            return HttpHelper::error('invalid slot');
        }

        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body) || !isset($body['item_id']) || !is_string($body['item_id'])) {
            return HttpHelper::error('invalid item_id');
        }
        $itemId = $body['item_id'];

        if (!isset(self::EQUIPMENT_ITEMS[$itemId])) {
            return HttpHelper::error('invalid item_id');
        }
        if (self::EQUIPMENT_ITEMS[$itemId] !== $slot) {
            return HttpHelper::error('invalid slot');
        }

        $held = false;
        foreach ($this->storage->getPlayCampaignCharacterInventoryItems($campaignId, $characterId) as $entry) {
            if ($entry['item_id'] === $itemId && $entry['quantity'] > 0) {
                $held = true;
                break;
            }
        }
        if (!$held) {
            return HttpHelper::error('item not held');
        }

        $this->storage->setPlayCampaignCharacterEquipment($campaignId, $characterId, $slot, $itemId, false);

        return new JsonResponse([
            'character_id' => $characterId,
            'slot' => $slot,
            'item_id' => $itemId,
            'attuned' => false,
        ]);
    }

    public function getPlayCampaignCharacterEquipment(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $this->auth->requirePlayCampaignMemberOrOwner($request, $campaign);

        $characterId = $parameters['character_id'] ?? '';
        $character = $this->storage->getPlayCampaignMemberByCharacterId($campaignId, $characterId);
        if ($character === null) {
            return new JsonResponse(['error' => 'character not found'], 404);
        }

        $slot = $parameters['slot'] ?? '';
        if (!in_array($slot, ['armor', 'accessory'], true)) {
            return HttpHelper::error('invalid slot');
        }

        $equipment = $this->storage->getPlayCampaignCharacterEquipment($campaignId, $characterId, $slot);
        if ($equipment === null) {
            return new JsonResponse([
                'character_id' => $characterId,
                'slot' => $slot,
                'item_id' => '',
                'attuned' => false,
            ]);
        }

        return new JsonResponse([
            'character_id' => $characterId,
            'slot' => $slot,
            'item_id' => $equipment['item_id'],
            'attuned' => $equipment['attuned'],
        ]);
    }

    public function attunePlayCampaignCharacterItem(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $characterId = $parameters['character_id'] ?? '';
        $character = $this->storage->getPlayCampaignMemberByCharacterId($campaignId, $characterId);
        if ($character === null) {
            return new JsonResponse(['error' => 'character not found'], 404);
        }

        if ($character['owner'] !== $user['username']) {
            return new JsonResponse(['error' => 'forbidden'], 403);
        }

        $slot = $parameters['slot'] ?? '';
        if (!in_array($slot, ['armor', 'accessory'], true)) {
            return HttpHelper::error('invalid slot');
        }

        $equipment = $this->storage->getPlayCampaignCharacterEquipment($campaignId, $characterId, $slot);
        if ($equipment === null || $equipment['item_id'] === '') {
            return HttpHelper::error('no item equipped');
        }
        $itemId = $equipment['item_id'];

        if (!in_array($itemId, self::ATTUNABLE_ITEMS, true)) {
            return HttpHelper::error('item is not attunable');
        }

        $attunedCount = $this->storage->getPlayCampaignCharacterAttunementCount($campaignId, $characterId);
        if ($attunedCount >= self::MAX_ATTUNEMENTS) {
            return new JsonResponse(['error' => 'max attunements reached'], 409);
        }

        $this->storage->setPlayCampaignCharacterEquipment($campaignId, $characterId, $slot, $itemId, true);

        return new JsonResponse([
            'character_id' => $characterId,
            'slot' => $slot,
            'item_id' => $itemId,
            'attuned' => true,
            'attunement_count' => $attunedCount + 1,
            'max_attunements' => self::MAX_ATTUNEMENTS,
        ]);
    }

    public function consumePlayCampaignCharacterItem(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $characterId = $parameters['character_id'] ?? '';
        $character = $this->storage->getPlayCampaignMemberByCharacterId($campaignId, $characterId);
        if ($character === null) {
            return new JsonResponse(['error' => 'character not found'], 404);
        }

        if ($character['owner'] !== $user['username']) {
            return new JsonResponse(['error' => 'forbidden'], 403);
        }

        $itemId = $parameters['item_id'] ?? '';
        if (!in_array($itemId, self::PLAY_CAMPAIGN_INVENTORY_ITEMS, true)) {
            return HttpHelper::error('invalid item_id');
        }
        if ($itemId !== 'healing-potion') {
            return HttpHelper::error('item is not consumable');
        }

        $remaining = $this->storage->removePlayCampaignCharacterInventoryItem($campaignId, $characterId, $itemId, 1);
        if ($remaining === null) {
            return new JsonResponse(['error' => 'insufficient quantity'], 409);
        }

        $this->storage->healPlayCampaignCharacterByConsumption($campaignId, $characterId, 5);

        return new JsonResponse([
            'character_id' => $characterId,
            'item_id' => $itemId,
            'quantity_consumed' => 1,
            'total_quantity' => $remaining,
            'effect' => [
                'type' => 'healing',
                'hp_restored' => 5,
            ],
        ], 200);
    }

    public function createPlayCampaignRecipe(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireDm($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $this->auth->requirePlayCampaignOwner($request, $campaign);

        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body)) {
            return HttpHelper::error('invalid json');
        }
        if (!isset($body['recipe_id']) || !is_string($body['recipe_id']) || $body['recipe_id'] === '') {
            return HttpHelper::error('invalid recipe_id');
        }
        if (!isset($body['name']) || !is_string($body['name']) || $body['name'] === '') {
            return HttpHelper::error('invalid name');
        }
        if (!isset($body['ingredients']) || !is_array($body['ingredients']) || count($body['ingredients']) === 0) {
            return HttpHelper::error('invalid ingredients');
        }
        $ingredients = [];
        foreach ($body['ingredients'] as $itemId => $quantity) {
            if (!is_string($itemId) || !in_array($itemId, self::PLAY_CAMPAIGN_INVENTORY_ITEMS, true)) {
                return HttpHelper::error('invalid ingredients');
            }
            if (!is_int($quantity) || $quantity <= 0) {
                return HttpHelper::error('invalid ingredients');
            }
            $ingredients[$itemId] = $quantity;
        }
        if (!isset($body['output_item']) || !is_string($body['output_item']) || !in_array($body['output_item'], self::PLAY_CAMPAIGN_INVENTORY_ITEMS, true)) {
            return HttpHelper::error('invalid output_item');
        }
        if (!isset($body['output_quantity']) || !is_int($body['output_quantity']) || $body['output_quantity'] <= 0) {
            return HttpHelper::error('invalid output_quantity');
        }

        if (!$this->storage->createPlayCampaignRecipe($campaignId, $body['recipe_id'], $body['name'], $ingredients, $body['output_item'], $body['output_quantity'])) {
            return new JsonResponse(['error' => 'recipe already exists'], 409);
        }

        return new JsonResponse([
            'recipe_id' => $body['recipe_id'],
            'name' => $body['name'],
            'ingredients' => $ingredients,
            'output_item' => $body['output_item'],
            'output_quantity' => $body['output_quantity'],
        ], 201);
    }

    public function listPlayCampaignRecipes(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $this->auth->requirePlayCampaignMemberOrOwner($request, $campaign);

        return new JsonResponse(['recipes' => $this->storage->getPlayCampaignRecipes($campaignId)]);
    }

    public function craftPlayCampaignRecipe(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $recipeId = $parameters['recipe_id'] ?? '';
        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body) || !isset($body['character_id']) || !is_string($body['character_id']) || $body['character_id'] === '') {
            return HttpHelper::error('invalid character_id');
        }
        $characterId = $body['character_id'];

        $recipe = $this->storage->getPlayCampaignRecipe($campaignId, $recipeId);
        if ($recipe === null) {
            return new JsonResponse(['error' => 'recipe not found'], 404);
        }

        $character = $this->storage->getPlayCampaignMemberByCharacterId($campaignId, $characterId);
        if ($character === null) {
            return new JsonResponse(['error' => 'character not found'], 404);
        }

        if ($user['role'] === 'dm' || $user['username'] === $campaign['owner']) {
            return new JsonResponse(['error' => 'forbidden'], 403);
        }
        if ($character['owner'] !== $user['username']) {
            return new JsonResponse(['error' => 'forbidden'], 403);
        }

        $result = $this->storage->craftPlayCampaignRecipe($campaignId, $recipeId, $characterId);
        if ($result === null) {
            return new JsonResponse(['error' => 'recipe not found'], 404);
        }
        if (isset($result['error'])) {
            return new JsonResponse(['error' => $result['error']], 409);
        }

        return new JsonResponse($result, 201);
    }

    public function getCharacterCurrency(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $this->auth->requirePlayCampaignMemberOrOwner($request, $campaign);

        $characterId = $parameters['character_id'] ?? '';
        $currency = $this->storage->getCharacterCurrency($campaignId, $characterId);
        if ($currency === null) {
            return new JsonResponse(['error' => 'character not found'], 404);
        }

        return new JsonResponse($currency);
    }

    public function transferCharacterCurrency(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $this->auth->requirePlayCampaignMemberOrOwner($request, $campaign);

        $characterId = $parameters['character_id'] ?? '';
        $character = $this->storage->getPlayCampaignMemberByCharacterId($campaignId, $characterId);
        if ($character === null) {
            return new JsonResponse(['error' => 'character not found'], 404);
        }

        if ($character['owner'] !== $user['username']) {
            return new JsonResponse(['error' => 'forbidden'], 403);
        }

        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body)) {
            return HttpHelper::error('invalid json');
        }
        if (!isset($body['to_character_id']) || !is_string($body['to_character_id']) || $body['to_character_id'] === '') {
            return HttpHelper::error('invalid to_character_id');
        }
        if (!isset($body['gold']) || !is_int($body['gold']) || $body['gold'] <= 0) {
            return HttpHelper::error('invalid gold');
        }

        $toCharacterId = $body['to_character_id'];
        $gold = $body['gold'];

        if ($toCharacterId === $characterId) {
            return HttpHelper::error('invalid to_character_id');
        }

        $toCharacter = $this->storage->getPlayCampaignMemberByCharacterId($campaignId, $toCharacterId);
        if ($toCharacter === null) {
            return HttpHelper::error('invalid to_character_id');
        }

        $result = $this->storage->transferGold($campaignId, $characterId, $toCharacterId, $gold);
        if ($result === null) {
            return new JsonResponse(['error' => 'character not found'], 404);
        }
        if (isset($result['error'])) {
            return new JsonResponse(['error' => 'insufficient gold'], 409);
        }

        return new JsonResponse([
            'from_character_id' => $characterId,
            'to_character_id' => $toCharacterId,
            'gold' => $gold,
            'from_gold' => $result['from_gold'],
            'to_gold' => $result['to_gold'],
            'transfer_id' => $result['transfer_id'],
        ], 201);
    }

    public function createTransactionalTransfer(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $this->auth->requirePlayCampaignMemberOrOwner($request, $campaign);

        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body)) {
            return HttpHelper::error('invalid json');
        }
        if (!isset($body['from_character_id']) || !is_string($body['from_character_id']) || $body['from_character_id'] === '') {
            return HttpHelper::error('invalid from_character_id');
        }
        if (!isset($body['to_character_id']) || !is_string($body['to_character_id']) || $body['to_character_id'] === '') {
            return HttpHelper::error('invalid to_character_id');
        }
        if (!isset($body['amount']) || !is_int($body['amount']) || $body['amount'] <= 0) {
            return HttpHelper::error('invalid amount');
        }
        if (array_key_exists('simulate_failure', $body) && !is_bool($body['simulate_failure'])) {
            return HttpHelper::error('invalid simulate_failure');
        }

        $fromCharacterId = $body['from_character_id'];
        $toCharacterId = $body['to_character_id'];
        $amount = $body['amount'];
        $simulateFailure = $body['simulate_failure'] ?? false;

        $fromCharacter = $this->storage->getPlayCampaignMemberByCharacterId($campaignId, $fromCharacterId);
        if ($fromCharacter === null) {
            return HttpHelper::error('invalid from_character_id');
        }
        if ($fromCharacter['owner'] !== $user['username']) {
            return new JsonResponse(['error' => 'forbidden'], 403);
        }

        $toCharacter = $this->storage->getPlayCampaignMemberByCharacterId($campaignId, $toCharacterId);
        if ($toCharacter === null) {
            return HttpHelper::error('invalid to_character_id');
        }

        if ($toCharacterId === $fromCharacterId) {
            return HttpHelper::error('invalid to_character_id');
        }

        $result = $this->storage->createTransactionalTransfer($campaignId, $fromCharacterId, $toCharacterId, $amount, $simulateFailure);
        if ($result === null) {
            return HttpHelper::error('invalid from_character_id');
        }
        if (isset($result['error'])) {
            $status = $result['error'] === 'simulated failure' ? 500 : 409;

            return new JsonResponse(['error' => $result['error']], $status);
        }

        return new JsonResponse($result, 201);
    }

    public function getTransactionalTransfers(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $this->auth->requirePlayCampaignMemberOrOwner($request, $campaign);

        $transfers = $this->storage->getTransactionalTransfers($campaignId);

        return new JsonResponse(['transfers' => $transfers]);
    }

    private function mapEncounterActive(?array $active): ?array
    {
        return $this->mapEncounterCombatant($active);
    }

    private function mapEncounterCombatant(?array $combatant): ?array
    {
        if ($combatant === null) {
            return null;
        }

        $kind = $combatant['kind'] ?? null;
        if ($kind === 'member') {
            $kind = 'player';
        }

        return [
            'name' => $combatant['name'],
            'kind' => $kind,
            'initiative' => $combatant['initiative'],
        ];
    }

    public function createPlayCampaignLoot(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireDm($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $this->auth->requirePlayCampaignOwner($request, $campaign);

        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body)) {
            return HttpHelper::error('invalid json');
        }
        if (!isset($body['loot_id']) || !is_string($body['loot_id']) || $body['loot_id'] === '') {
            return HttpHelper::error('invalid loot_id');
        }
        if (!isset($body['item_id']) || !is_string($body['item_id']) || !in_array($body['item_id'], self::PLAY_CAMPAIGN_INVENTORY_ITEMS, true)) {
            return HttpHelper::error('invalid item_id');
        }
        if (!isset($body['quantity']) || !is_int($body['quantity']) || $body['quantity'] <= 0) {
            return HttpHelper::error('invalid quantity');
        }

        $loot = $this->storage->createPlayCampaignLoot($campaignId, $body['loot_id'], $body['item_id'], $body['quantity']);
        if ($loot === null) {
            return new JsonResponse(['error' => 'loot already exists'], 409);
        }

        return new JsonResponse($loot, 201);
    }

    public function votePlayCampaignLoot(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requirePlayer($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        if (!$this->storage->isPlayCampaignMember($campaignId, $user['username'])) {
            return new JsonResponse(['error' => 'forbidden'], 403);
        }

        $lootId = $parameters['loot_id'] ?? '';
        $loot = $this->storage->getPlayCampaignLoot($campaignId, $lootId);
        if ($loot === null) {
            return new JsonResponse(['error' => 'loot not found'], 404);
        }
        if ($loot['status'] !== 'open') {
            return new JsonResponse(['error' => 'loot is not open'], 409);
        }

        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body)) {
            return HttpHelper::error('invalid json');
        }
        if (!isset($body['recipient_character_id']) || !is_string($body['recipient_character_id']) || $body['recipient_character_id'] === '') {
            return HttpHelper::error('invalid recipient_character_id');
        }

        $recipient = $this->storage->getPlayCampaignMemberByCharacterId($campaignId, $body['recipient_character_id']);
        if ($recipient === null) {
            return HttpHelper::error('character not found');
        }

        $result = $this->storage->addPlayCampaignLootVote($campaignId, $lootId, $user['username'], $body['recipient_character_id']);
        if ($result === null) {
            return new JsonResponse(['error' => 'vote already exists'], 409);
        }

        return new JsonResponse([
            'loot_id' => $lootId,
            'voter' => $user['username'],
            'recipient_character_id' => $body['recipient_character_id'],
            'votes_for_recipient' => $result['votes_for_recipient'],
        ], 201);
    }

    public function assignPlayCampaignLoot(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireDm($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $this->auth->requirePlayCampaignOwner($request, $campaign);

        $lootId = $parameters['loot_id'] ?? '';
        $loot = $this->storage->getPlayCampaignLoot($campaignId, $lootId);
        if ($loot === null) {
            return new JsonResponse(['error' => 'loot not found'], 404);
        }

        $result = $this->storage->assignPlayCampaignLoot($campaignId, $lootId);
        if ($result === null) {
            return new JsonResponse(['error' => 'loot already assigned'], 409);
        }
        if (isset($result['error'])) {
            return new JsonResponse(['error' => $result['error']], 409);
        }

        return new JsonResponse($result, 200);
    }

    public function getPlayCampaignLoot(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $this->auth->requirePlayCampaignMemberOrOwner($request, $campaign);

        $lootId = $parameters['loot_id'] ?? '';
        $loot = $this->storage->getPlayCampaignLoot($campaignId, $lootId);
        if ($loot === null) {
            return new JsonResponse(['error' => 'loot not found'], 404);
        }

        $votes = $this->storage->getPlayCampaignLootVotes($campaignId, $lootId);
        $tallies = [];
        foreach ($votes as $vote) {
            $recipient = $vote['recipient_character_id'];
            $tallies[$recipient] = ($tallies[$recipient] ?? 0) + 1;
        }
        ksort($tallies);

        return new JsonResponse([
            'loot_id' => $loot['loot_id'],
            'item_id' => $loot['item_id'],
            'quantity' => $loot['quantity'],
            'status' => $loot['status'],
            'recipient_character_id' => $loot['recipient_character_id'],
            'votes' => $tallies,
        ]);
    }

    public function createPlayCampaignNpc(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireDm($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $this->auth->requirePlayCampaignOwner($request, $campaign);

        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body)) {
            return HttpHelper::error('invalid json');
        }

        foreach (['npc_id', 'name', 'agenda', 'public_status'] as $key) {
            if (!isset($body[$key]) || !is_string($body[$key]) || $body[$key] === '') {
                return HttpHelper::error("invalid {$key}");
            }
        }

        $npcId = $body['npc_id'];
        $name = $body['name'];
        $agenda = $body['agenda'];
        $publicStatus = $body['public_status'];

        if (!$this->storage->createPlayCampaignNpc($campaignId, $npcId, $name, $agenda, $publicStatus)) {
            return new JsonResponse(['error' => 'npc already exists'], 409);
        }

        return new JsonResponse([
            'npc_id' => $npcId,
            'name' => $name,
            'agenda' => $agenda,
            'public_status' => $publicStatus,
        ], 201);
    }

    public function updatePlayCampaignNpcAgenda(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireDm($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $this->auth->requirePlayCampaignOwner($request, $campaign);

        $npcId = $parameters['npc_id'] ?? '';
        $npc = $this->storage->getPlayCampaignNpc($campaignId, $npcId);
        if ($npc === null) {
            return new JsonResponse(['error' => 'npc not found'], 404);
        }

        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body)) {
            return HttpHelper::error('invalid json');
        }

        foreach (['agenda', 'public_status'] as $key) {
            if (!isset($body[$key]) || !is_string($body[$key]) || $body[$key] === '') {
                return HttpHelper::error("invalid {$key}");
            }
        }

        $agenda = $body['agenda'];
        $publicStatus = $body['public_status'];

        $this->storage->updatePlayCampaignNpcAgenda($campaignId, $npcId, $agenda, $publicStatus);

        return new JsonResponse([
            'npc_id' => $npc['npc_id'],
            'name' => $npc['name'],
            'agenda' => $agenda,
            'public_status' => $publicStatus,
        ], 200);
    }

    public function getPlayCampaignNpc(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        [$user, $isOwner] = $this->auth->requirePlayCampaignMemberOrOwner($request, $campaign);

        $npcId = $parameters['npc_id'] ?? '';
        $npc = $this->storage->getPlayCampaignNpc($campaignId, $npcId);
        if ($npc === null) {
            return new JsonResponse(['error' => 'npc not found'], 404);
        }

        if ($isOwner) {
            return new JsonResponse([
                'npc_id' => $npc['npc_id'],
                'name' => $npc['name'],
                'agenda' => $npc['agenda'],
                'public_status' => $npc['public_status'],
            ]);
        }

        return new JsonResponse([
            'npc_id' => $npc['npc_id'],
            'name' => $npc['name'],
            'public_status' => $npc['public_status'],
        ]);
    }

    public function createPlayCampaignFaction(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireDm($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $this->auth->requirePlayCampaignOwner($request, $campaign);

        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body)) {
            return HttpHelper::error('invalid json');
        }
        if (!isset($body['faction_id']) || !is_string($body['faction_id']) || $body['faction_id'] === '') {
            return HttpHelper::error('invalid faction_id');
        }
        if (!isset($body['name']) || !is_string($body['name']) || $body['name'] === '') {
            return HttpHelper::error('invalid name');
        }

        $factionId = $body['faction_id'];
        $name = $body['name'];

        if (!$this->storage->createPlayCampaignFaction($campaignId, $factionId, $name)) {
            return new JsonResponse(['error' => 'faction already exists'], 409);
        }

        return new JsonResponse([
            'faction_id' => $factionId,
            'name' => $name,
        ], 201);
    }

    public function changePlayCampaignReputation(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireDm($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $this->auth->requirePlayCampaignOwner($request, $campaign);

        $factionId = $parameters['faction_id'] ?? '';
        if ($this->storage->getPlayCampaignFaction($campaignId, $factionId) === null) {
            return new JsonResponse(['error' => 'faction not found'], 404);
        }

        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body)) {
            return HttpHelper::error('invalid json');
        }
        if (!isset($body['character_id']) || !is_string($body['character_id']) || $body['character_id'] === '') {
            return HttpHelper::error('invalid character_id');
        }
        if (!isset($body['delta']) || !is_int($body['delta']) || $body['delta'] === 0 || $body['delta'] < -25 || $body['delta'] > 25) {
            return HttpHelper::error('invalid delta');
        }
        if (!isset($body['reason']) || !is_string($body['reason']) || $body['reason'] === '') {
            return HttpHelper::error('invalid reason');
        }

        $characterId = $body['character_id'];
        if ($this->storage->getPlayCampaignMemberByCharacterId($campaignId, $characterId) === null) {
            return HttpHelper::error('character not found');
        }

        $entry = $this->storage->addPlayCampaignReputationEntry($campaignId, $factionId, $characterId, $body['delta'], $body['reason']);

        return new JsonResponse([
            'faction_id' => $entry['faction_id'],
            'character_id' => $entry['character_id'],
            'reputation' => $entry['total_reputation'],
            'delta' => $entry['delta'],
            'reason' => $entry['reason'],
        ], 201);
    }

    public function getPlayCampaignReputation(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        [$user, $isOwner] = $this->auth->requirePlayCampaignMemberOrOwner($request, $campaign);

        $factionId = $parameters['faction_id'] ?? '';
        if ($this->storage->getPlayCampaignFaction($campaignId, $factionId) === null) {
            return new JsonResponse(['error' => 'faction not found'], 404);
        }

        if ($isOwner) {
            $entries = $this->storage->getPlayCampaignReputationHistory($campaignId, $factionId);
        } else {
            $member = $this->storage->getPlayCampaignMember($campaignId, $user['username']);
            $entries = $member !== null
                ? $this->storage->getPlayCampaignReputationHistory($campaignId, $factionId, $member['character_id'])
                : [];
        }

        return new JsonResponse([
            'faction_id' => $factionId,
            'entries' => $entries,
        ]);
    }

    public function addPlayCampaignNpcDialogue(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireDm($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $this->auth->requirePlayCampaignOwner($request, $campaign);

        $npcId = $parameters['npc_id'] ?? '';
        if ($this->storage->getPlayCampaignNpc($campaignId, $npcId) === null) {
            return new JsonResponse(['error' => 'npc not found'], 404);
        }

        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body)) {
            return HttpHelper::error('invalid json');
        }
        if (!isset($body['dialogue_id']) || !is_string($body['dialogue_id']) || $body['dialogue_id'] === '') {
            return HttpHelper::error('invalid dialogue_id');
        }
        if (!isset($body['speaker']) || !is_string($body['speaker']) || $body['speaker'] === '') {
            return HttpHelper::error('invalid speaker');
        }
        if (!isset($body['text']) || !is_string($body['text']) || $body['text'] === '') {
            return HttpHelper::error('invalid text');
        }
        if (!isset($body['visibility']) || !is_string($body['visibility']) || ($body['visibility'] !== 'public' && $body['visibility'] !== 'private')) {
            return HttpHelper::error('invalid visibility');
        }

        if (!$this->storage->addPlayCampaignNpcDialogue($campaignId, $npcId, $body['dialogue_id'], $body['speaker'], $body['text'], $body['visibility'])) {
            return new JsonResponse(['error' => 'dialogue_id already exists'], 409);
        }

        return new JsonResponse([
            'dialogue_id' => $body['dialogue_id'],
            'speaker' => $body['speaker'],
            'text' => $body['text'],
            'visibility' => $body['visibility'],
        ], 201);
    }

    public function getPlayCampaignNpcDialogue(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        [$user, $isOwner] = $this->auth->requirePlayCampaignMemberOrOwner($request, $campaign);

        $npcId = $parameters['npc_id'] ?? '';
        if ($this->storage->getPlayCampaignNpc($campaignId, $npcId) === null) {
            return new JsonResponse(['error' => 'npc not found'], 404);
        }

        $entries = $isOwner
            ? $this->storage->getPlayCampaignNpcDialogue($campaignId, $npcId)
            : $this->storage->getPlayCampaignNpcDialogue($campaignId, $npcId, 'public');

        return new JsonResponse([
            'npc_id' => $npcId,
            'entries' => $entries,
        ]);
    }

    public function createPlayCampaignRelationship(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireDm($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $this->auth->requirePlayCampaignOwner($request, $campaign);

        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body)) {
            return HttpHelper::error('invalid json');
        }
        if (!isset($body['source_id']) || !is_string($body['source_id']) || $body['source_id'] === '') {
            return HttpHelper::error('invalid source_id');
        }
        if (!isset($body['target_id']) || !is_string($body['target_id']) || $body['target_id'] === '') {
            return HttpHelper::error('invalid target_id');
        }
        if (!isset($body['kind']) || !is_string($body['kind']) || $body['kind'] === '') {
            return HttpHelper::error('invalid kind');
        }
        if (!isset($body['score']) || !is_int($body['score'])) {
            return HttpHelper::error('invalid score');
        }

        $sourceId = $body['source_id'];
        $targetId = $body['target_id'];
        $kind = $body['kind'];
        $score = $body['score'];

        if ($sourceId === $targetId) {
            return HttpHelper::error('self-edges are not allowed');
        }
        if ($score < -100 || $score > 100) {
            return HttpHelper::error('invalid score');
        }

        if (!$this->storage->playCampaignEntityExists($campaignId, $sourceId)) {
            return new JsonResponse(['error' => 'source entity not found'], 404);
        }
        if (!$this->storage->playCampaignEntityExists($campaignId, $targetId)) {
            return new JsonResponse(['error' => 'target entity not found'], 404);
        }

        if (!$this->storage->addPlayCampaignRelationship($campaignId, $sourceId, $targetId, $kind, $score)) {
            return new JsonResponse(['error' => 'relationship already exists'], 409);
        }

        return new JsonResponse([
            'source_id' => $sourceId,
            'target_id' => $targetId,
            'kind' => $kind,
            'score' => $score,
        ], 201);
    }

    public function updatePlayCampaignRelationship(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireDm($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $this->auth->requirePlayCampaignOwner($request, $campaign);

        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body)) {
            return HttpHelper::error('invalid json');
        }
        if (!isset($body['score']) || !is_int($body['score'])) {
            return HttpHelper::error('invalid score');
        }

        $score = $body['score'];
        if ($score < -100 || $score > 100) {
            return HttpHelper::error('invalid score');
        }

        $sourceId = $parameters['source_id'] ?? '';
        $targetId = $parameters['target_id'] ?? '';
        $kind = $parameters['kind'] ?? '';

        $existing = $this->storage->getPlayCampaignRelationship($campaignId, $sourceId, $targetId, $kind);
        if ($existing === null) {
            return new JsonResponse(['error' => 'relationship not found'], 404);
        }

        $this->storage->updatePlayCampaignRelationshipScore($campaignId, $sourceId, $targetId, $kind, $score);

        return new JsonResponse([
            'source_id' => $sourceId,
            'target_id' => $targetId,
            'kind' => $kind,
            'score' => $score,
        ], 200);
    }

    public function getPlayCampaignRelationships(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $this->auth->requirePlayCampaignMemberOrOwner($request, $campaign);

        return new JsonResponse([
            'edges' => $this->storage->getPlayCampaignRelationships($campaignId),
        ]);
    }

    public function createPlayCampaignClue(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireDm($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $this->auth->requirePlayCampaignOwner($request, $campaign);

        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body)) {
            return HttpHelper::error('invalid json');
        }
        if (!isset($body['clue_id']) || !is_string($body['clue_id']) || $body['clue_id'] === '') {
            return HttpHelper::error('invalid clue_id');
        }
        if (!isset($body['text']) || !is_string($body['text']) || $body['text'] === '') {
            return HttpHelper::error('invalid text');
        }
        if (!isset($body['audience']) || !is_string($body['audience']) || !in_array($body['audience'], ['character', 'party', 'hidden'], true)) {
            return HttpHelper::error('invalid audience');
        }

        $clueId = $body['clue_id'];
        $text = $body['text'];
        $audience = $body['audience'];
        $characterId = null;

        if ($audience === 'character') {
            if (!isset($body['character_id']) || !is_string($body['character_id']) || $body['character_id'] === '') {
                return HttpHelper::error('invalid character_id');
            }
            $characterId = $body['character_id'];
            if ($this->storage->getPlayCampaignMemberByCharacterId($campaignId, $characterId) === null) {
                return HttpHelper::error('character not found');
            }
        } elseif (array_key_exists('character_id', $body)) {
            return HttpHelper::error('invalid character_id');
        }

        if (!$this->storage->createPlayCampaignClue($campaignId, $clueId, $text, $audience, $characterId)) {
            return new JsonResponse(['error' => 'clue already exists'], 409);
        }

        $response = [
            'clue_id' => $clueId,
            'text' => $text,
            'audience' => $audience,
        ];
        if ($characterId !== null) {
            $response['character_id'] = $characterId;
        }

        return new JsonResponse($response, 201);
    }

    public function getPlayCampaignClues(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        [$user, $isOwner] = $this->auth->requirePlayCampaignMemberOrOwner($request, $campaign);

        $clues = $this->storage->getPlayCampaignClues($campaignId);

        if (!$isOwner) {
            $member = $this->storage->getPlayCampaignMember($campaignId, $user['username']);
            $ownCharacterId = $member !== null ? $member['character_id'] : null;
            $filtered = [];
            foreach ($clues as $clue) {
                if ($clue['audience'] === 'party') {
                    $filtered[] = $clue;
                } elseif ($clue['audience'] === 'character' && $ownCharacterId !== null && ($clue['character_id'] ?? null) === $ownCharacterId) {
                    $filtered[] = $clue;
                }
            }
            $clues = $filtered;
        }

        return new JsonResponse(['clues' => $clues]);
    }

    public function createPlayCampaignQuest(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $this->auth->requirePlayCampaignOwner($request, $campaign);

        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body)) {
            return HttpHelper::error('invalid json');
        }
        if (!isset($body['quest_id']) || !is_string($body['quest_id']) || $body['quest_id'] === '') {
            return HttpHelper::error('invalid quest_id');
        }
        if (!isset($body['title']) || !is_string($body['title']) || $body['title'] === '') {
            return HttpHelper::error('invalid title');
        }
        if (!isset($body['depends_on']) || !is_array($body['depends_on'])) {
            return HttpHelper::error('invalid depends_on');
        }

        $questId = $body['quest_id'];
        $title = $body['title'];
        $dependsOn = [];
        $seen = [];
        foreach ($body['depends_on'] as $dep) {
            if (!is_string($dep) || $dep === '') {
                return HttpHelper::error('invalid depends_on');
            }
            if (isset($seen[$dep])) {
                return HttpHelper::error('invalid depends_on');
            }
            $seen[$dep] = true;
            $dependsOn[] = $dep;
        }

        if (in_array($questId, $dependsOn, true)) {
            return HttpHelper::error('invalid depends_on');
        }

        foreach ($dependsOn as $dep) {
            if ($this->storage->getPlayCampaignQuest($campaignId, $dep) === null) {
                return HttpHelper::error('invalid depends_on');
            }
        }

        if (!$this->storage->createPlayCampaignQuest($campaignId, $questId, $title, $dependsOn)) {
            return new JsonResponse(['error' => 'quest already exists'], 409);
        }

        return new JsonResponse([
            'quest_id' => $questId,
            'title' => $title,
            'depends_on' => $dependsOn,
            'state' => 'locked',
        ], 201);
    }

    public function updatePlayCampaignQuestState(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $this->auth->requirePlayCampaignOwner($request, $campaign);

        $questId = $parameters['quest_id'] ?? '';
        $quest = $this->storage->getPlayCampaignQuest($campaignId, $questId);
        if ($quest === null) {
            return new JsonResponse(['error' => 'quest not found'], 404);
        }

        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body) || !isset($body['state']) || !is_string($body['state']) || ($body['state'] !== 'active' && $body['state'] !== 'completed')) {
            return HttpHelper::error('invalid state');
        }

        $newState = $body['state'];
        $currentState = $quest['state'];

        if ($newState === 'active') {
            if ($currentState !== 'locked') {
                return new JsonResponse(['error' => 'invalid transition'], 409);
            }
            foreach ($quest['depends_on'] as $dep) {
                $depQuest = $this->storage->getPlayCampaignQuest($campaignId, $dep);
                if ($depQuest === null || $depQuest['state'] !== 'completed') {
                    return new JsonResponse(['error' => 'dependencies not completed'], 409);
                }
            }
        } elseif ($newState === 'completed') {
            if ($currentState !== 'active') {
                return new JsonResponse(['error' => 'invalid transition'], 409);
            }
        }

        $this->storage->updatePlayCampaignQuestState($campaignId, $questId, $newState);
        $updatedQuest = $this->storage->getPlayCampaignQuest($campaignId, $questId);

        $response = [
            'quest_id' => $updatedQuest['quest_id'],
            'title' => $updatedQuest['title'],
            'depends_on' => $updatedQuest['depends_on'],
            'state' => $updatedQuest['state'],
        ];
        if (!empty($updatedQuest['rewards'])) {
            $response['rewards'] = [
                'xp' => $updatedQuest['rewards']['xp'] ?? 0,
                'items' => (object) ($updatedQuest['rewards']['items'] ?? []),
            ];
        }

        return new JsonResponse($response, 200);
    }

    public function getPlayCampaignQuests(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $this->auth->requirePlayCampaignMemberOrOwner($request, $campaign);

        $quests = $this->storage->getPlayCampaignQuests($campaignId);

        return new JsonResponse(['quests' => $quests]);
    }

    public function configurePlayCampaignQuestRewards(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $this->auth->requirePlayCampaignOwner($request, $campaign);

        $questId = $parameters['quest_id'] ?? '';
        $quest = $this->storage->getPlayCampaignQuest($campaignId, $questId);
        if ($quest === null) {
            return new JsonResponse(['error' => 'quest not found'], 404);
        }

        if ($quest['state'] !== 'locked' && $quest['state'] !== 'active') {
            return new JsonResponse(['error' => 'quest already completed'], 409);
        }

        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body)) {
            return HttpHelper::error('invalid json');
        }
        if (!isset($body['xp']) || !is_int($body['xp']) || $body['xp'] < 0) {
            return HttpHelper::error('invalid xp');
        }
        if (!isset($body['items']) || !is_array($body['items'])) {
            return HttpHelper::error('invalid items');
        }

        $items = [];
        foreach ($body['items'] as $itemId => $qty) {
            if (!is_string($itemId) || $itemId === '' || !is_int($qty) || $qty <= 0) {
                return HttpHelper::error('invalid items');
            }
            if (!in_array($itemId, self::PLAY_CAMPAIGN_INVENTORY_ITEMS, true)) {
                return HttpHelper::error('invalid items');
            }
            $items[$itemId] = $qty;
        }

        $updated = $this->storage->setPlayCampaignQuestRewards($campaignId, $questId, $body['xp'], $items);
        if ($updated === null) {
            return new JsonResponse(['error' => 'quest not found'], 404);
        }
        if (isset($updated['error'])) {
            return new JsonResponse(['error' => 'quest already completed'], 409);
        }

        return new JsonResponse([
            'quest_id' => $updated['quest_id'],
            'title' => $updated['title'],
            'depends_on' => $updated['depends_on'],
            'state' => $updated['state'],
            'rewards' => [
                'xp' => $updated['rewards']['xp'] ?? 0,
                'items' => (object) ($updated['rewards']['items'] ?? []),
            ],
        ], 200);
    }

    public function awardPlayCampaignQuestRewards(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $this->auth->requirePlayCampaignOwner($request, $campaign);

        $questId = $parameters['quest_id'] ?? '';
        $quest = $this->storage->getPlayCampaignQuest($campaignId, $questId);
        if ($quest === null) {
            return new JsonResponse(['error' => 'quest not found'], 404);
        }

        $result = $this->storage->awardPlayCampaignQuestRewards($campaignId, $questId);
        if ($result === null) {
            return new JsonResponse(['error' => 'quest not found'], 404);
        }
        if (isset($result['error'])) {
            return new JsonResponse(['error' => 'quest not completed or rewards not configured'], 409);
        }

        return new JsonResponse([
            'quest_id' => $questId,
            'awarded' => true,
            'xp' => $result['xp'],
            'items' => (object) $result['items'],
        ], 201);
    }

    public function getPlayCampaignCharacterRewards(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        [$user, $isOwner] = $this->auth->requirePlayCampaignMemberOrOwner($request, $campaign);

        $characterId = $parameters['character_id'] ?? '';
        $rewards = $this->storage->getPlayCampaignCharacterRewards($campaignId, $characterId);
        if ($rewards === null) {
            return new JsonResponse(['error' => 'character not found'], 404);
        }

        return new JsonResponse([
            'character_id' => $characterId,
            'xp' => $rewards['xp'],
            'items' => (object) $rewards['items'],
        ]);
    }

    public function schedulePlayCampaignWorldEvent(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireDm($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $this->auth->requirePlayCampaignOwner($request, $campaign);

        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body)) {
            return HttpHelper::error('invalid json');
        }
        if (!isset($body['event_id']) || !is_string($body['event_id']) || $body['event_id'] === '') {
            return HttpHelper::error('invalid event_id');
        }
        if (!isset($body['turn_number']) || !is_int($body['turn_number'])) {
            return HttpHelper::error('invalid turn_number');
        }
        if (!isset($body['title']) || !is_string($body['title']) || $body['title'] === '') {
            return HttpHelper::error('invalid title');
        }
        if (!isset($body['text']) || !is_string($body['text']) || $body['text'] === '') {
            return HttpHelper::error('invalid text');
        }

        if ($body['turn_number'] < $campaign['turn_number']) {
            return HttpHelper::error('invalid turn_number');
        }

        if (!$this->storage->createPlayCampaignWorldEvent($campaignId, $body['event_id'], $body['turn_number'], $body['title'], $body['text'])) {
            return new JsonResponse(['error' => 'event already exists'], 409);
        }

        return new JsonResponse([
            'event_id' => $body['event_id'],
            'turn_number' => $body['turn_number'],
            'title' => $body['title'],
            'text' => $body['text'],
            'status' => 'scheduled',
        ], 201);
    }

    public function resolvePlayCampaignWorldEvent(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireDm($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $this->auth->requirePlayCampaignOwner($request, $campaign);

        $eventId = $parameters['event_id'] ?? '';
        $event = $this->storage->getPlayCampaignWorldEvent($campaignId, $eventId);
        if ($event === null) {
            return new JsonResponse(['error' => 'event not found'], 404);
        }

        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body)) {
            return HttpHelper::error('invalid json');
        }
        if (!isset($body['text']) || !is_string($body['text']) || $body['text'] === '') {
            return HttpHelper::error('invalid text');
        }

        if ($campaign['turn_number'] !== $event['turn_number']) {
            return new JsonResponse(['error' => 'turn mismatch'], 409);
        }

        $result = $this->storage->resolvePlayCampaignWorldEvent($campaignId, $eventId, $body['text'], $campaign['turn_number']);
        if ($result === null) {
            return new JsonResponse(['error' => 'event not found'], 404);
        }
        if (isset($result['error'])) {
            return new JsonResponse(['error' => 'event already resolved'], 409);
        }

        return new JsonResponse($result, 201);
    }

    public function getPlayCampaignWorldEvents(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $this->auth->requirePlayCampaignMemberOrOwner($request, $campaign);

        return new JsonResponse([
            'events' => $this->storage->getPlayCampaignWorldEvents($campaignId),
        ]);
    }

    public function createPlayCampaignCalendar(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireDm($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $this->auth->requirePlayCampaignOwner($request, $campaign);

        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body)) {
            return HttpHelper::error('invalid json');
        }
        if (!isset($body['day']) || !is_int($body['day']) || $body['day'] < 1) {
            return HttpHelper::error('invalid day');
        }
        if (!isset($body['season']) || !is_string($body['season']) || !in_array($body['season'], Calendar::seasons(), true)) {
            return HttpHelper::error('invalid season');
        }

        if (!$this->storage->createPlayCampaignCalendar($campaignId, $body['day'], $body['season'])) {
            return new JsonResponse(['error' => 'calendar already exists'], 409);
        }

        return new JsonResponse([
            'day' => $body['day'],
            'season' => $body['season'],
            'weather' => Calendar::weather($body['day'], $body['season']),
        ], 201);
    }

    public function getPlayCampaignCalendar(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $this->auth->requirePlayCampaignMemberOrOwner($request, $campaign);

        $calendar = $this->storage->getPlayCampaignCalendar($campaignId);
        if ($calendar === null) {
            return new JsonResponse(['error' => 'calendar not found'], 404);
        }

        return new JsonResponse([
            'day' => $calendar['day'],
            'season' => $calendar['season'],
            'weather' => Calendar::weather($calendar['day'], $calendar['season']),
        ]);
    }

    public function advancePlayCampaignCalendar(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireDm($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $this->auth->requirePlayCampaignOwner($request, $campaign);

        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body)) {
            return HttpHelper::error('invalid json');
        }
        if (!isset($body['days']) || !is_int($body['days']) || $body['days'] < 1 || $body['days'] > 30) {
            return HttpHelper::error('invalid days');
        }

        $calendar = $this->storage->advancePlayCampaignCalendar($campaignId, $body['days']);
        if ($calendar === null) {
            return new JsonResponse(['error' => 'calendar not found'], 404);
        }

        return new JsonResponse([
            'day' => $calendar['day'],
            'season' => $calendar['season'],
            'weather' => Calendar::weather($calendar['day'], $calendar['season']),
        ]);
    }

    public function createPlayCampaignSettlement(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireDm($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $this->auth->requirePlayCampaignOwner($request, $campaign);

        $body = HttpHelper::parseJsonBody($request);
        $validated = $this->validateSettlementPayload($body, true);
        if ($validated instanceof JsonResponse) {
            return $validated;
        }

        [$settlementId, $name, $services, $availability] = $validated;

        if (!$this->storage->createPlayCampaignSettlement($campaignId, $settlementId, $name, $services, $availability)) {
            return new JsonResponse(['error' => 'settlement already exists'], 409);
        }

        return new JsonResponse([
            'settlement_id' => $settlementId,
            'name' => $name,
            'services' => $services,
            'availability' => $availability,
            'discovered_by' => [],
        ], 201);
    }

    public function updatePlayCampaignSettlement(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireDm($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $this->auth->requirePlayCampaignOwner($request, $campaign);

        $settlementId = $parameters['settlement_id'] ?? '';
        $settlement = $this->storage->getPlayCampaignSettlement($campaignId, $settlementId);
        if ($settlement === null) {
            return new JsonResponse(['error' => 'settlement not found'], 404);
        }

        $body = HttpHelper::parseJsonBody($request);
        $validated = $this->validateSettlementPayload($body, false);
        if ($validated instanceof JsonResponse) {
            return $validated;
        }

        [, $name, $services, $availability] = $validated;

        $this->storage->updatePlayCampaignSettlement($campaignId, $settlementId, $name, $services, $availability);

        return new JsonResponse([
            'settlement_id' => $settlementId,
            'name' => $name,
            'services' => $services,
            'availability' => $availability,
            'discovered_by' => $settlement['discovered_by'],
        ], 200);
    }

    public function discoverPlayCampaignSettlement(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requirePlayer($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        if ($campaign['owner'] === $user['username']) {
            return new JsonResponse(['error' => 'forbidden'], 403);
        }
        if (!$this->storage->isPlayCampaignMember($campaignId, $user['username'])) {
            return new JsonResponse(['error' => 'forbidden'], 403);
        }

        $settlementId = $parameters['settlement_id'] ?? '';
        $settlement = $this->storage->getPlayCampaignSettlement($campaignId, $settlementId);
        if ($settlement === null) {
            return new JsonResponse(['error' => 'settlement not found'], 404);
        }

        $member = $this->storage->getPlayCampaignMember($campaignId, $user['username']);
        if ($member === null) {
            return new JsonResponse(['error' => 'forbidden'], 403);
        }
        $characterId = $member['character_id'];

        try {
            $appended = $this->storage->discoverPlayCampaignSettlement($campaignId, $settlementId, $characterId);
        } catch (\RuntimeException) {
            return new JsonResponse(['error' => 'settlement not found'], 404);
        }

        $status = $appended ? 201 : 200;

        return new JsonResponse([
            'settlement_id' => $settlement['settlement_id'],
            'name' => $settlement['name'],
            'services' => $settlement['services'],
            'availability' => $settlement['availability'],
            'discovered_by' => [$characterId],
        ], $status);
    }

    public function getPlayCampaignSettlements(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        [$user, $isOwner] = $this->auth->requirePlayCampaignMemberOrOwner($request, $campaign);

        $settlements = $this->storage->getPlayCampaignSettlements($campaignId);

        if ($isOwner) {
            return new JsonResponse(['settlements' => $settlements]);
        }

        $member = $this->storage->getPlayCampaignMember($campaignId, $user['username']);
        $ownCharacterId = $member !== null ? $member['character_id'] : null;

        $filtered = [];
        foreach ($settlements as $settlement) {
            if ($ownCharacterId !== null && in_array($ownCharacterId, $settlement['discovered_by'], true)) {
                $filtered[] = [
                    'settlement_id' => $settlement['settlement_id'],
                    'name' => $settlement['name'],
                    'services' => $settlement['services'],
                    'availability' => $settlement['availability'],
                    'discovered_by' => [$ownCharacterId],
                ];
            }
        }

        return new JsonResponse(['settlements' => $filtered]);
    }

    public function createPlayCampaignShop(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireDm($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $this->auth->requirePlayCampaignOwner($request, $campaign);

        $settlementId = $parameters['settlement_id'] ?? '';
        $settlement = $this->storage->getPlayCampaignSettlement($campaignId, $settlementId);
        if ($settlement === null) {
            return new JsonResponse(['error' => 'settlement not found'], 404);
        }

        $body = HttpHelper::parseJsonBody($request);
        $validated = $this->validateShopPayload($body);
        if ($validated instanceof JsonResponse) {
            return $validated;
        }

        [$shopId, $name, $stock, $buyPrice, $sellPrice] = $validated;

        if (!$this->storage->createPlayCampaignShop($campaignId, $settlementId, $shopId, $name, $stock, $buyPrice, $sellPrice)) {
            return new JsonResponse(['error' => 'shop already exists'], 409);
        }

        return new JsonResponse([
            'shop_id' => $shopId,
            'name' => $name,
            'stock' => $stock,
            'buy_price' => $buyPrice,
            'sell_price' => $sellPrice,
        ], 201);
    }

    public function getPlayCampaignShop(Request $request, array $parameters): JsonResponse
    {
        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        [$user, $isOwner] = $this->auth->requirePlayCampaignMemberOrOwner($request, $campaign);

        $settlementId = $parameters['settlement_id'] ?? '';
        $settlement = $this->storage->getPlayCampaignSettlement($campaignId, $settlementId);
        if ($settlement === null) {
            return new JsonResponse(['error' => 'settlement not found'], 404);
        }

        $shopId = $parameters['shop_id'] ?? '';
        $shop = $this->storage->getPlayCampaignShop($campaignId, $settlementId, $shopId);
        if ($shop === null) {
            return new JsonResponse(['error' => 'shop not found'], 404);
        }

        if (!$isOwner) {
            $member = $this->storage->getPlayCampaignMember($campaignId, $user['username']);
            $ownCharacterId = $member !== null ? $member['character_id'] : null;
            if ($ownCharacterId === null || !in_array($ownCharacterId, $settlement['discovered_by'], true)) {
                return new JsonResponse(['error' => 'shop not found'], 404);
            }
        }

        return new JsonResponse($shop);
    }

    public function buyFromPlayCampaignShop(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requirePlayer($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $settlementId = $parameters['settlement_id'] ?? '';
        $settlement = $this->storage->getPlayCampaignSettlement($campaignId, $settlementId);
        if ($settlement === null) {
            return new JsonResponse(['error' => 'settlement not found'], 404);
        }

        $shopId = $parameters['shop_id'] ?? '';
        $shop = $this->storage->getPlayCampaignShop($campaignId, $settlementId, $shopId);
        if ($shop === null) {
            return new JsonResponse(['error' => 'shop not found'], 404);
        }

        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body)) {
            return HttpHelper::error('invalid json');
        }
        if (!isset($body['character_id']) || !is_string($body['character_id']) || $body['character_id'] === '') {
            return HttpHelper::error('invalid character_id');
        }
        if (!isset($body['item_id']) || !is_string($body['item_id']) || !in_array($body['item_id'], self::PLAY_CAMPAIGN_INVENTORY_ITEMS, true)) {
            return HttpHelper::error('invalid item_id');
        }
        if (!isset($body['quantity']) || !is_int($body['quantity']) || $body['quantity'] <= 0) {
            return HttpHelper::error('invalid quantity');
        }

        $characterId = $body['character_id'];
        $itemId = $body['item_id'];
        $quantity = $body['quantity'];

        $character = $this->storage->getPlayCampaignMemberByCharacterId($campaignId, $characterId);
        if ($character === null) {
            return new JsonResponse(['error' => 'character not found'], 404);
        }
        if ($character['owner'] !== $user['username']) {
            return new JsonResponse(['error' => 'forbidden'], 403);
        }

        try {
            $result = $this->storage->buyFromShop($campaignId, $settlementId, $shopId, $characterId, $itemId, $quantity);
        } catch (\RuntimeException $e) {
            $message = $e->getMessage();
            if ($message === 'insufficient stock' || $message === 'insufficient gold') {
                return new JsonResponse(['error' => 'insufficient ' . explode(' ', $message)[1]], 409);
            }
            throw $e;
        }
        if ($result === null) {
            return new JsonResponse(['error' => 'shop not found'], 404);
        }

        return new JsonResponse([
            'character_id' => $characterId,
            'item_id' => $itemId,
            'quantity' => $quantity,
            'gold' => $result['gold'],
            'stock' => $result['stock'],
        ], 200);
    }

    public function sellToPlayCampaignShop(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requirePlayer($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $settlementId = $parameters['settlement_id'] ?? '';
        $settlement = $this->storage->getPlayCampaignSettlement($campaignId, $settlementId);
        if ($settlement === null) {
            return new JsonResponse(['error' => 'settlement not found'], 404);
        }

        $shopId = $parameters['shop_id'] ?? '';
        $shop = $this->storage->getPlayCampaignShop($campaignId, $settlementId, $shopId);
        if ($shop === null) {
            return new JsonResponse(['error' => 'shop not found'], 404);
        }

        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body)) {
            return HttpHelper::error('invalid json');
        }
        if (!isset($body['character_id']) || !is_string($body['character_id']) || $body['character_id'] === '') {
            return HttpHelper::error('invalid character_id');
        }
        if (!isset($body['item_id']) || !is_string($body['item_id']) || !in_array($body['item_id'], self::PLAY_CAMPAIGN_INVENTORY_ITEMS, true)) {
            return HttpHelper::error('invalid item_id');
        }
        if (!isset($body['quantity']) || !is_int($body['quantity']) || $body['quantity'] <= 0) {
            return HttpHelper::error('invalid quantity');
        }

        $characterId = $body['character_id'];
        $itemId = $body['item_id'];
        $quantity = $body['quantity'];

        $character = $this->storage->getPlayCampaignMemberByCharacterId($campaignId, $characterId);
        if ($character === null) {
            return new JsonResponse(['error' => 'character not found'], 404);
        }
        if ($character['owner'] !== $user['username']) {
            return new JsonResponse(['error' => 'forbidden'], 403);
        }

        try {
            $result = $this->storage->sellToShop($campaignId, $settlementId, $shopId, $characterId, $itemId, $quantity);
        } catch (\RuntimeException $e) {
            if ($e->getMessage() === 'insufficient inventory') {
                return new JsonResponse(['error' => 'insufficient inventory'], 409);
            }
            throw $e;
        }
        if ($result === null) {
            return new JsonResponse(['error' => 'shop not found'], 404);
        }

        return new JsonResponse([
            'character_id' => $characterId,
            'item_id' => $itemId,
            'quantity' => $quantity,
            'gold' => $result['gold'],
            'stock' => $result['stock'],
        ], 200);
    }

    public function createPlayCampaignDowntimeActivity(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireDm($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $this->auth->requirePlayCampaignOwner($request, $campaign);

        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body)) {
            return HttpHelper::error('invalid json');
        }
        if (!isset($body['activity_id']) || !is_string($body['activity_id']) || $body['activity_id'] === '') {
            return HttpHelper::error('invalid activity_id');
        }
        if (!isset($body['name']) || !is_string($body['name']) || $body['name'] === '') {
            return HttpHelper::error('invalid name');
        }
        if (!isset($body['cycles_required']) || !is_int($body['cycles_required']) || $body['cycles_required'] < 1 || $body['cycles_required'] > 10) {
            return HttpHelper::error('invalid cycles_required');
        }

        if (!$this->storage->createPlayCampaignDowntimeActivity($campaignId, $body['activity_id'], $body['name'], $body['cycles_required'])) {
            return new JsonResponse(['error' => 'activity already exists'], 409);
        }

        return new JsonResponse([
            'activity_id' => $body['activity_id'],
            'name' => $body['name'],
            'cycles_required' => $body['cycles_required'],
        ], 201);
    }

    public function createPlayCampaignDowntimeAllocation(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requirePlayer($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $characterId = $parameters['character_id'] ?? '';
        $character = $this->storage->getPlayCampaignMemberByCharacterId($campaignId, $characterId);
        if ($character === null) {
            return new JsonResponse(['error' => 'character not found'], 404);
        }
        if ($character['owner'] !== $user['username']) {
            return new JsonResponse(['error' => 'forbidden'], 403);
        }

        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body) || !isset($body['activity_id']) || !is_string($body['activity_id']) || $body['activity_id'] === '') {
            return HttpHelper::error('invalid activity_id');
        }
        $activityId = $body['activity_id'];

        $activity = $this->storage->getPlayCampaignDowntimeActivity($campaignId, $activityId);
        if ($activity === null) {
            return new JsonResponse(['error' => 'activity not found'], 404);
        }

        if (!$this->storage->createPlayCampaignDowntimeAllocation($campaignId, $characterId, $activityId)) {
            return new JsonResponse(['error' => 'allocation already exists'], 409);
        }

        return new JsonResponse([
            'character_id' => $characterId,
            'activity_id' => $activityId,
            'cycles_completed' => 0,
            'completions' => 0,
        ], 201);
    }

    public function progressPlayCampaignDowntimeAllocation(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requirePlayer($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $characterId = $parameters['character_id'] ?? '';
        $character = $this->storage->getPlayCampaignMemberByCharacterId($campaignId, $characterId);
        if ($character === null) {
            return new JsonResponse(['error' => 'character not found'], 404);
        }
        if ($character['owner'] !== $user['username']) {
            return new JsonResponse(['error' => 'forbidden'], 403);
        }

        $activityId = $parameters['activity_id'] ?? '';
        $activity = $this->storage->getPlayCampaignDowntimeActivity($campaignId, $activityId);
        if ($activity === null) {
            return new JsonResponse(['error' => 'activity not found'], 404);
        }

        $allocation = $this->storage->getPlayCampaignDowntimeAllocation($campaignId, $characterId, $activityId);
        if ($allocation === null) {
            return new JsonResponse(['error' => 'allocation not found'], 404);
        }

        $updated = $this->storage->progressPlayCampaignDowntimeAllocation($campaignId, $characterId, $activityId);
        if ($updated === null) {
            return new JsonResponse(['error' => 'allocation not found'], 404);
        }

        return new JsonResponse($updated);
    }

    public function getPlayCampaignDowntimeAllocation(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        [$user, $isOwner] = $this->auth->requirePlayCampaignMemberOrOwner($request, $campaign);

        $characterId = $parameters['character_id'] ?? '';
        $character = $this->storage->getPlayCampaignMemberByCharacterId($campaignId, $characterId);
        if ($character === null) {
            return new JsonResponse(['error' => 'character not found'], 404);
        }

        $activityId = $parameters['activity_id'] ?? '';
        $activity = $this->storage->getPlayCampaignDowntimeActivity($campaignId, $activityId);
        if ($activity === null) {
            return new JsonResponse(['error' => 'activity not found'], 404);
        }

        $allocation = $this->storage->getPlayCampaignDowntimeAllocation($campaignId, $characterId, $activityId);
        if ($allocation === null) {
            return new JsonResponse(['error' => 'allocation not found'], 404);
        }

        return new JsonResponse($allocation);
    }

    /**
     * Validate a settlement create/update payload.
     *
     * Returns an array [settlementId, name, services, availability] on success
     * or a JsonResponse error on failure. For updates the returned settlementId
     * is empty and should be taken from the path.
     */
    private function validateSettlementPayload(?array $body, bool $requireId): array|JsonResponse
    {
        if (!is_array($body)) {
            return HttpHelper::error('invalid json');
        }

        if ($requireId) {
            if (!isset($body['settlement_id']) || !is_string($body['settlement_id']) || $body['settlement_id'] === '') {
                return HttpHelper::error('invalid settlement_id');
            }
            $settlementId = $body['settlement_id'];
        } else {
            $settlementId = '';
        }

        if (!isset($body['name']) || !is_string($body['name']) || $body['name'] === '') {
            return HttpHelper::error('invalid name');
        }

        if (!isset($body['services']) || !is_array($body['services']) || count($body['services']) === 0) {
            return HttpHelper::error('invalid services');
        }
        $services = [];
        $seen = [];
        foreach ($body['services'] as $service) {
            if (!is_string($service)) {
                return HttpHelper::error('invalid services');
            }
            $normalized = trim($service);
            if ($normalized === '') {
                return HttpHelper::error('invalid services');
            }
            if (isset($seen[$normalized])) {
                return HttpHelper::error('invalid services');
            }
            $seen[$normalized] = true;
            $services[] = $normalized;
        }

        if (!isset($body['availability']) || !is_string($body['availability']) || !in_array($body['availability'], ['open', 'limited', 'closed'], true)) {
            return HttpHelper::error('invalid availability');
        }

        return [$settlementId, $body['name'], $services, $body['availability']];
    }

    /**
     * Validate a shop create payload.
     *
     * Returns an array [shopId, name, stock, buyPrice, sellPrice] on success
     * or a JsonResponse error on failure.
     */
    private function validateShopPayload(?array $body): array|JsonResponse
    {
        if (!is_array($body)) {
            return HttpHelper::error('invalid json');
        }

        if (!isset($body['shop_id']) || !is_string($body['shop_id']) || $body['shop_id'] === '') {
            return HttpHelper::error('invalid shop_id');
        }

        if (!isset($body['name']) || !is_string($body['name']) || $body['name'] === '') {
            return HttpHelper::error('invalid name');
        }

        if (!isset($body['stock']) || !is_array($body['stock']) || count($body['stock']) === 0) {
            return HttpHelper::error('invalid stock');
        }
        $stock = [];
        foreach ($body['stock'] as $itemId => $qty) {
            if (!is_string($itemId) || $itemId === '' || !in_array($itemId, self::PLAY_CAMPAIGN_INVENTORY_ITEMS, true)) {
                return HttpHelper::error('invalid stock');
            }
            if (!is_int($qty) || $qty <= 0) {
                return HttpHelper::error('invalid stock');
            }
            $stock[$itemId] = $qty;
        }

        if (!isset($body['buy_price']) || !is_int($body['buy_price']) || $body['buy_price'] <= 0) {
            return HttpHelper::error('invalid buy_price');
        }

        if (!isset($body['sell_price']) || !is_int($body['sell_price']) || $body['sell_price'] < 0) {
            return HttpHelper::error('invalid sell_price');
        }

        return [$body['shop_id'], $body['name'], $stock, $body['buy_price'], $body['sell_price']];
    }

    public function createPlayCampaignNote(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        [$user, $isOwner] = $this->auth->requirePlayCampaignMemberOrOwner($request, $campaign);

        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body)) {
            return HttpHelper::error('invalid json');
        }
        if (!isset($body['note_id']) || !is_string($body['note_id']) || $body['note_id'] === '') {
            return HttpHelper::error('invalid note_id');
        }
        if (!isset($body['text']) || !is_string($body['text']) || $body['text'] === '') {
            return HttpHelper::error('invalid text');
        }
        if (!isset($body['visibility']) || !is_string($body['visibility']) || ($body['visibility'] !== 'private' && $body['visibility'] !== 'party')) {
            return HttpHelper::error('invalid visibility');
        }

        $noteId = $body['note_id'];
        $text = $body['text'];
        $visibility = $body['visibility'];

        if (!$this->storage->createPlayCampaignNote($campaignId, $noteId, $text, $visibility, $user['username'])) {
            return new JsonResponse(['error' => 'note already exists'], 409);
        }

        return new JsonResponse([
            'note_id' => $noteId,
            'text' => $text,
            'visibility' => $visibility,
            'owner' => $user['username'],
        ], 201);
    }

    public function getPlayCampaignNotes(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        [$user, $isOwner] = $this->auth->requirePlayCampaignMemberOrOwner($request, $campaign);

        $notes = $this->storage->getPlayCampaignNotes($campaignId);
        if ($isOwner) {
            return new JsonResponse(['notes' => $notes]);
        }

        $filtered = [];
        foreach ($notes as $note) {
            if ($note['visibility'] === 'party' || $note['owner'] === $user['username']) {
                $filtered[] = $note;
            }
        }

        return new JsonResponse(['notes' => $filtered]);
    }

    public function getPlayCampaignNote(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        [$user, $isOwner] = $this->auth->requirePlayCampaignMemberOrOwner($request, $campaign);

        $noteId = $parameters['note_id'] ?? '';
        $note = $this->storage->getPlayCampaignNote($campaignId, $noteId);
        if ($note === null) {
            return new JsonResponse(['error' => 'note not found'], 404);
        }

        if (!$isOwner && $note['visibility'] === 'private' && $note['owner'] !== $user['username']) {
            throw new HttpException('forbidden', 403);
        }

        return new JsonResponse($note);
    }

    public function updatePlayCampaignNote(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $this->auth->requirePlayCampaignMemberOrOwner($request, $campaign);

        $noteId = $parameters['note_id'] ?? '';
        $note = $this->storage->getPlayCampaignNote($campaignId, $noteId);
        if ($note === null) {
            return new JsonResponse(['error' => 'note not found'], 404);
        }

        if ($note['owner'] !== $user['username']) {
            throw new HttpException('forbidden', 403);
        }

        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body)) {
            return HttpHelper::error('invalid json');
        }
        if (!isset($body['text']) || !is_string($body['text']) || $body['text'] === '') {
            return HttpHelper::error('invalid text');
        }
        if (!isset($body['visibility']) || !is_string($body['visibility']) || ($body['visibility'] !== 'private' && $body['visibility'] !== 'party')) {
            return HttpHelper::error('invalid visibility');
        }

        $text = $body['text'];
        $visibility = $body['visibility'];

        $this->storage->updatePlayCampaignNote($campaignId, $noteId, $text, $visibility);

        return new JsonResponse([
            'note_id' => $noteId,
            'text' => $text,
            'visibility' => $visibility,
            'owner' => $note['owner'],
        ], 200);
    }

    public function createPlayCampaignWhisper(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requirePlayer($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }
        if (!$this->storage->isPlayCampaignMember($campaignId, $user['username'])) {
            return new JsonResponse(['error' => 'forbidden'], 403);
        }

        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body)) {
            return HttpHelper::error('invalid json');
        }
        if (!isset($body['whisper_id']) || !is_string($body['whisper_id']) || $body['whisper_id'] === '') {
            return HttpHelper::error('invalid whisper_id');
        }
        if (!isset($body['to_character_id']) || !is_string($body['to_character_id']) || $body['to_character_id'] === '') {
            return HttpHelper::error('invalid to_character_id');
        }
        if (!isset($body['text']) || !is_string($body['text']) || $body['text'] === '') {
            return HttpHelper::error('invalid text');
        }

        $whisperId = $body['whisper_id'];
        $toCharacterId = $body['to_character_id'];
        $text = $body['text'];

        $member = $this->storage->getPlayCampaignMember($campaignId, $user['username']);
        if ($member === null) {
            return new JsonResponse(['error' => 'forbidden'], 403);
        }
        $fromCharacterId = $member['character_id'];

        if ($this->storage->getPlayCampaignMemberByCharacterId($campaignId, $toCharacterId) === null) {
            return HttpHelper::error('invalid to_character_id');
        }

        if (!$this->storage->createPlayCampaignWhisper($campaignId, $whisperId, $fromCharacterId, $toCharacterId, $text)) {
            return new JsonResponse(['error' => 'whisper already exists'], 409);
        }

        return new JsonResponse([
            'whisper_id' => $whisperId,
            'from_character_id' => $fromCharacterId,
            'to_character_id' => $toCharacterId,
            'text' => $text,
        ], 201);
    }

    public function getPlayCampaignWhispers(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        [$user, $isOwner] = $this->auth->requirePlayCampaignMemberOrOwner($request, $campaign);

        $whispers = $this->storage->getPlayCampaignWhispers($campaignId);
        if ($isOwner) {
            return new JsonResponse(['whispers' => $whispers]);
        }

        $member = $this->storage->getPlayCampaignMember($campaignId, $user['username']);
        $ownCharacterId = $member !== null ? $member['character_id'] : null;

        $filtered = [];
        foreach ($whispers as $whisper) {
            if ($whisper['from_character_id'] === $ownCharacterId || $whisper['to_character_id'] === $ownCharacterId) {
                $filtered[] = $whisper;
            }
        }

        return new JsonResponse(['whispers' => $filtered]);
    }

    public function createPlayCampaignMessage(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        [$user, $isOwner] = $this->auth->requirePlayCampaignMemberOrOwner($request, $campaign);

        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body)) {
            return HttpHelper::error('invalid json');
        }
        if (!isset($body['text']) || !is_string($body['text']) || $body['text'] === '') {
            return HttpHelper::error('invalid text');
        }

        $messageId = $body['message_id'] ?? uniqid('msg-', true);
        if (!is_string($messageId) || $messageId === '') {
            return HttpHelper::error('invalid message_id');
        }
        $text = $body['text'];

        if (!$this->storage->createPlayCampaignMessage($campaignId, $messageId, $user['username'], $text)) {
            return new JsonResponse(['error' => 'message already exists'], 409);
        }

        return new JsonResponse([
            'message_id' => $messageId,
            'kind' => 'chat',
            'actor' => $user['username'],
            'text' => $text,
        ], 201);
    }

    public function getPlayCampaignMessages(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $this->auth->requirePlayCampaignMemberOrOwner($request, $campaign);

        return new JsonResponse(['messages' => $this->storage->getPlayCampaignMessages($campaignId)]);
    }

    public function getPlayCampaignCharacterSheet(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        [$user, $isOwner] = $this->auth->requirePlayCampaignMemberOrOwner($request, $campaign);

        $characterId = $parameters['character_id'] ?? '';
        $sheet = $this->storage->getPlayCampaignCharacterSheet($campaignId, $characterId);
        if ($sheet === null) {
            return new JsonResponse(['error' => 'character not found'], 404);
        }

        if (!$isOwner && $sheet['owner'] !== $user['username']) {
            throw new HttpException('forbidden', 403);
        }

        return new JsonResponse($sheet);
    }

    public function createPlayCampaignInvitation(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $this->auth->requirePlayCampaignOwner($request, $campaign);

        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body)) {
            return HttpHelper::error('invalid json');
        }
        if (!isset($body['invitation_id']) || !is_string($body['invitation_id']) || $body['invitation_id'] === '') {
            return HttpHelper::error('invalid invitation_id');
        }
        if (!isset($body['username']) || !is_string($body['username']) || $body['username'] === '') {
            return HttpHelper::error('invalid username');
        }
        if (!isset($body['character_id']) || !is_string($body['character_id']) || $body['character_id'] === '') {
            return HttpHelper::error('invalid character_id');
        }

        $target = $this->storage->getUser($body['username']);
        if ($target === null || $target['role'] !== 'player') {
            return HttpHelper::error('invalid target user');
        }

        if (!$this->storage->createPlayCampaignInvitation($campaignId, $body['invitation_id'], $body['username'], $body['character_id'])) {
            return new JsonResponse(['error' => 'invitation already exists'], 409);
        }

        return new JsonResponse([
            'invitation_id' => $body['invitation_id'],
            'username' => $body['username'],
            'character_id' => $body['character_id'],
            'status' => 'pending',
        ], 201);
    }

    public function acceptPlayCampaignInvitation(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $invitationId = $parameters['invitation_id'] ?? '';
        $invitation = $this->storage->getPlayCampaignInvitation($campaignId, $invitationId);
        if ($invitation === null) {
            return new JsonResponse(['error' => 'invitation not found'], 404);
        }

        if ($invitation['username'] !== $user['username']) {
            return new JsonResponse(['error' => 'forbidden'], 403);
        }

        $result = $this->storage->acceptPlayCampaignInvitation($campaignId, $invitationId, $user['username']);
        if ($result === null) {
            return new JsonResponse(['error' => 'invitation not found'], 404);
        }
        if (isset($result['error'])) {
            return new JsonResponse(['error' => 'invitation already accepted'], 409);
        }

        return new JsonResponse($result, 200);
    }

    public function listPlayCampaignInvitations(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $isOwner = $campaign['owner'] === $user['username'];
        $invitations = $this->storage->getPlayCampaignInvitations($campaignId);

        if ($isOwner) {
            return new JsonResponse(['invitations' => $invitations]);
        }

        $hasInvitation = false;
        foreach ($invitations as $invitation) {
            if ($invitation['username'] === $user['username']) {
                $hasInvitation = true;
                break;
            }
        }

        if ($hasInvitation) {
            $filtered = [];
            foreach ($invitations as $invitation) {
                if ($invitation['username'] === $user['username']) {
                    $filtered[] = $invitation;
                }
            }

            return new JsonResponse(['invitations' => $filtered]);
        }

        if ($this->storage->isPlayCampaignMember($campaignId, $user['username'])) {
            return new JsonResponse(['invitations' => []]);
        }

        return new JsonResponse(['error' => 'forbidden'], 403);
    }

    public function grantPlayCampaignDelegation(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $this->auth->requirePlayCampaignOwner($request, $campaign);

        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body)) {
            return HttpHelper::error('invalid json');
        }
        if (!isset($body['username']) || !is_string($body['username']) || $body['username'] === '') {
            return HttpHelper::error('invalid username');
        }
        if (!isset($body['powers']) || !is_array($body['powers']) || count($body['powers']) === 0) {
            return HttpHelper::error('invalid powers');
        }

        $seen = [];
        $powers = [];
        foreach ($body['powers'] as $power) {
            if (!is_string($power) || $power !== 'narrate') {
                return HttpHelper::error('invalid powers');
            }
            if (isset($seen[$power])) {
                return HttpHelper::error('invalid powers');
            }
            $seen[$power] = true;
            $powers[] = $power;
        }

        if (!$this->storage->isPlayCampaignMember($campaignId, $body['username'])) {
            return HttpHelper::error('invalid target');
        }

        $result = $this->storage->grantPlayCampaignDelegation($campaignId, $body['username'], $powers);
        if ($result === null || isset($result['error'])) {
            return new JsonResponse(['error' => 'delegate already exists'], 409);
        }

        return new JsonResponse($result, 201);
    }

    public function revokePlayCampaignDelegation(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $this->auth->requirePlayCampaignOwner($request, $campaign);

        $username = $parameters['username'] ?? '';
        $result = $this->storage->revokePlayCampaignDelegation($campaignId, $username);
        if ($result === null) {
            return new JsonResponse(['error' => 'delegation not found'], 404);
        }

        return new JsonResponse($result, 200);
    }

    public function auditPlayCampaignDelegation(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $this->auth->requirePlayCampaignOwner($request, $campaign);

        $entries = $this->storage->getPlayCampaignDelegationAudit($campaignId);

        return new JsonResponse(['entries' => $entries]);
    }

    public function createPlayCampaignAuditEvent(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        [$user, $isOwner] = $this->auth->requirePlayCampaignMemberOrOwner($request, $campaign);
        $role = $isOwner ? 'DM' : 'player';

        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body)) {
            return HttpHelper::error('invalid json');
        }
        if (!isset($body['kind']) || !is_string($body['kind']) || $body['kind'] === '') {
            return HttpHelper::error('invalid kind');
        }
        if (!isset($body['correlation_id']) || !is_string($body['correlation_id']) || $body['correlation_id'] === '') {
            return HttpHelper::error('invalid correlation_id');
        }

        $result = $this->storage->createPlayCampaignAuditEvent($campaignId, $user['username'], $role, $body['kind'], $body['correlation_id']);
        if (isset($result['error'])) {
            return new JsonResponse(['error' => 'duplicate correlation_id'], 409);
        }

        return new JsonResponse($result, 201);
    }

    public function getPlayCampaignAuditEvents(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $this->auth->requirePlayCampaignOwner($request, $campaign);

        return new JsonResponse(['entries' => $this->storage->getPlayCampaignAuditEvents($campaignId)]);
    }

    public function createPlayCampaignProjectionEvent(Request $request, array $parameters): JsonResponse
    {
        $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        [$user, $isOwner] = $this->auth->requirePlayCampaignMemberOrOwner($request, $campaign);
        if ($isOwner) {
            return new JsonResponse(['error' => 'forbidden'], 403);
        }

        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body)) {
            return HttpHelper::error('invalid json');
        }
        if (!isset($body['event_id']) || !is_string($body['event_id']) || $body['event_id'] === '') {
            return HttpHelper::error('invalid event_id');
        }
        if (!isset($body['kind']) || !is_string($body['kind']) || ($body['kind'] !== 'set-story' && $body['kind'] !== 'increment-danger')) {
            return HttpHelper::error('invalid kind');
        }

        $kind = $body['kind'];
        $value = null;
        if ($kind === 'set-story') {
            if (!isset($body['value']) || !is_string($body['value']) || $body['value'] === '') {
                return HttpHelper::error('invalid value');
            }
            $value = $body['value'];
        } elseif (array_key_exists('value', $body)) {
            return HttpHelper::error('invalid value');
        }

        $event = $this->storage->createPlayCampaignProjectionEvent($campaignId, $body['event_id'], $kind, $value);
        if ($event === null) {
            return new JsonResponse(['error' => 'event already exists'], 409);
        }

        $response = [
            'sequence' => $event['sequence'],
            'event_id' => $event['event_id'],
            'kind' => $event['kind'],
        ];
        if ($event['value'] !== null) {
            $response['value'] = $event['value'];
        }

        return new JsonResponse($response, 201);
    }

    public function getPlayCampaignProjection(Request $request, array $parameters): JsonResponse
    {
        $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $this->auth->requirePlayCampaignMemberOrOwner($request, $campaign);

        return new JsonResponse($this->storage->buildPlayCampaignProjection($campaignId));
    }

    public function rebuildPlayCampaignProjection(Request $request, array $parameters): JsonResponse
    {
        $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $this->auth->requirePlayCampaignMemberOrOwner($request, $campaign);

        return new JsonResponse($this->storage->buildPlayCampaignProjection($campaignId));
    }

    public function createPlayCampaignIdempotentEvent(Request $request, array $parameters): JsonResponse
    {
        $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $this->auth->requirePlayCampaignMemberOrOwner($request, $campaign);

        $idempotencyKey = trim((string) $request->headers->get('Idempotency-Key', ''));
        if ($idempotencyKey === '') {
            return HttpHelper::error('invalid idempotency_key');
        }

        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body)) {
            return HttpHelper::error('invalid json');
        }
        if (!isset($body['event_id']) || !is_string($body['event_id']) || $body['event_id'] === '') {
            return HttpHelper::error('invalid event_id');
        }
        if (!isset($body['value']) || !is_string($body['value']) || $body['value'] === '') {
            return HttpHelper::error('invalid value');
        }

        $result = $this->storage->createPlayCampaignIdempotentEvent($campaignId, $body['event_id'], $body['value'], $idempotencyKey);
        if ($result['status'] === 'conflict') {
            return new JsonResponse(['error' => 'conflict'], 409);
        }

        $status = $result['status'] === 'created' ? 201 : 200;

        return new JsonResponse($result['event'], $status);
    }

    public function getPlayCampaignIdempotentEvents(Request $request, array $parameters): JsonResponse
    {
        $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $this->auth->requirePlayCampaignMemberOrOwner($request, $campaign);

        return new JsonResponse(['events' => $this->storage->getPlayCampaignIdempotentEvents($campaignId)]);
    }

    public function submitPlayCampaignSafeTurn(Request $request, array $parameters): JsonResponse
    {
        $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $this->auth->requirePlayCampaignMemberOrOwner($request, $campaign);

        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body)) {
            return HttpHelper::error('invalid json');
        }
        if (!isset($body['submission_id']) || !is_string($body['submission_id']) || $body['submission_id'] === '') {
            return HttpHelper::error('invalid submission_id');
        }
        if (!isset($body['action']) || !is_string($body['action']) || $body['action'] === '') {
            return HttpHelper::error('invalid action');
        }
        if (!isset($body['expected_turn']) || !is_int($body['expected_turn']) || $body['expected_turn'] <= 0) {
            return HttpHelper::error('invalid expected_turn');
        }

        $result = $this->storage->submitPlayCampaignSafeTurn($campaignId, $body['submission_id'], $body['action'], $body['expected_turn']);
        if ($result['status'] === 'accepted') {
            return new JsonResponse([
                'submission_id' => $result['submission_id'],
                'action' => $result['action'],
                'accepted_turn' => $result['accepted_turn'],
                'next_turn' => $result['next_turn'],
            ], 201);
        }

        return new JsonResponse(['current_turn' => $result['current_turn']], 409);
    }

    public function getPlayCampaignSafeTurns(Request $request, array $parameters): JsonResponse
    {
        $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $this->auth->requirePlayCampaignMemberOrOwner($request, $campaign);

        return new JsonResponse($this->storage->getPlayCampaignSafeTurnState($campaignId));
    }

    /**
     * Validate a session-zero settings payload.
     *
     * Returns an array [rules, tone, consent] on success or a JsonResponse error
     * on failure. Consent order is preserved and duplicates are rejected.
     */
    private function validateSessionZeroPayload(?array $body): array|JsonResponse
    {
        if (!is_array($body)) {
            return HttpHelper::error('invalid json');
        }

        if (!isset($body['rules']) || !is_string($body['rules']) || $body['rules'] === '') {
            return HttpHelper::error('invalid rules');
        }

        if (!isset($body['tone']) || !is_string($body['tone']) || $body['tone'] === '') {
            return HttpHelper::error('invalid tone');
        }

        if (!isset($body['consent']) || !is_array($body['consent']) || count($body['consent']) === 0) {
            return HttpHelper::error('invalid consent');
        }

        $seen = [];
        $consent = [];
        foreach ($body['consent'] as $value) {
            if (!is_string($value) || $value === '') {
                return HttpHelper::error('invalid consent');
            }
            if (isset($seen[$value])) {
                return HttpHelper::error('invalid consent');
            }
            $seen[$value] = true;
            $consent[] = $value;
        }

        return [
            'rules' => $body['rules'],
            'tone' => $body['tone'],
            'consent' => $consent,
        ];
    }

    public function createPlayCampaignImport(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        if ($campaign['owner'] !== $user['username']) {
            throw new HttpException('forbidden', 403);
        }

        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body)) {
            return HttpHelper::error('invalid import');
        }
        if (!isset($body['version']) || !is_int($body['version']) || $body['version'] !== 1) {
            return HttpHelper::error('invalid import');
        }
        if (!isset($body['story']) || !is_string($body['story']) || $body['story'] === '') {
            return HttpHelper::error('invalid import');
        }
        if (!isset($body['status']) || !is_string($body['status']) || !in_array($body['status'], ['lobby', 'started'], true)) {
            return HttpHelper::error('invalid import');
        }

        $result = $this->storage->createPlayCampaignImport($campaignId, $body['version'], $body['story'], $body['status']);
        if ($result === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        return new JsonResponse($result, 200);
    }

    public function getPlayCampaignImportState(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        if ($campaign['owner'] !== $user['username']) {
            throw new HttpException('forbidden', 403);
        }

        $state = $this->storage->getPlayCampaignImport($campaignId);
        if ($state === null) {
            return new JsonResponse(['error' => 'import not found'], 404);
        }

        return new JsonResponse($state);
    }

    public function createPlayCampaignMigration(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        if ($campaign['owner'] !== $user['username']) {
            throw new HttpException('forbidden', 403);
        }

        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body)) {
            return HttpHelper::error('invalid migration');
        }
        if (!isset($body['schema_version']) || !is_int($body['schema_version']) || $body['schema_version'] !== 1) {
            return HttpHelper::error('invalid migration');
        }
        if (!isset($body['story']) || !is_string($body['story']) || $body['story'] === '') {
            return HttpHelper::error('invalid migration');
        }

        $result = $this->storage->createPlayCampaignMigration($campaignId, $body['story'], $campaign['name']);
        $status = $result['created'] ? 201 : 200;
        unset($result['created']);

        return new JsonResponse($result, $status);
    }

    public function getPlayCampaignMigrationState(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        if ($campaign['owner'] !== $user['username']) {
            throw new HttpException('forbidden', 403);
        }

        $state = $this->storage->getPlayCampaignMigration($campaignId);
        if ($state === null) {
            return new JsonResponse(['error' => 'migration not found'], 404);
        }

        return new JsonResponse($state);
    }

    public function createPlayCampaignSearchRecord(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        if ($campaign['owner'] !== $user['username']) {
            return new JsonResponse(['error' => 'forbidden'], 403);
        }

        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body)) {
            return HttpHelper::error('invalid json');
        }
        if (!isset($body['record_id']) || !is_string($body['record_id']) || $body['record_id'] === '') {
            return HttpHelper::error('invalid record_id');
        }
        if (!isset($body['text']) || !is_string($body['text']) || $body['text'] === '') {
            return HttpHelper::error('invalid text');
        }

        if (!$this->storage->createPlayCampaignSearchRecord($campaignId, $body['record_id'], $body['text'])) {
            return new JsonResponse(['error' => 'record already exists'], 400);
        }

        return new JsonResponse([
            'record_id' => $body['record_id'],
            'text' => $body['text'],
        ], 201);
    }

    public function listPlayCampaignSearchRecords(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $this->auth->requirePlayCampaignMemberOrOwner($request, $campaign);

        $query = $request->query->get('q');
        if ($query !== null && !is_string($query)) {
            return HttpHelper::error('invalid q');
        }
        if ($query === '') {
            $query = null;
        }

        $limit = 2;
        $rawLimit = $request->query->get('limit');
        if ($rawLimit !== null) {
            if (!ctype_digit((string) $rawLimit)) {
                return HttpHelper::error('invalid limit');
            }
            $limit = (int) $rawLimit;
            if ($limit < 1 || $limit > 3) {
                return HttpHelper::error('invalid limit');
            }
        }

        $cursor = 0;
        $rawCursor = $request->query->get('cursor');
        if ($rawCursor !== null) {
            if (!ctype_digit((string) $rawCursor)) {
                return HttpHelper::error('invalid cursor');
            }
            $cursor = (int) $rawCursor;
        }

        return new JsonResponse($this->storage->listPlayCampaignSearchRecords($campaignId, $query, $cursor, $limit));
    }

    public function createPlayCampaignRateEvent(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $this->auth->requirePlayCampaignMemberOrOwner($request, $campaign);

        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body)) {
            return HttpHelper::error('invalid json');
        }
        if (!isset($body['event_id']) || !is_string($body['event_id']) || $body['event_id'] === '') {
            return HttpHelper::error('invalid event_id');
        }

        $result = $this->storage->createPlayCampaignRateEvent($campaignId, $body['event_id'], $user['username']);
        if ($result === null) {
            return HttpHelper::error('event already exists');
        }
        if (isset($result['error']) && $result['error'] === 'rate limited') {
            return new JsonResponse(['limit' => $result['limit'], 'remaining' => $result['remaining']], 429);
        }

        return new JsonResponse($result, 201);
    }

    public function listPlayCampaignRateEvents(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $this->auth->requirePlayCampaignMemberOrOwner($request, $campaign);

        return new JsonResponse($this->storage->listPlayCampaignRateEvents($campaignId, $user['username']));
    }

    public function getPlayCampaignMetrics(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $this->auth->requirePlayCampaignOwner($request, $campaign);

        return new JsonResponse($this->storage->getPlayCampaignMetrics($campaignId));
    }

    public function createPlayCampaignBackup(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $this->auth->requirePlayCampaignOwner($request, $campaign);

        $backup = $this->storage->createPlayCampaignBackup($campaignId);
        if ($backup === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        return new JsonResponse($backup, 201);
    }

    public function listPlayCampaignBackups(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $this->auth->requirePlayCampaignOwner($request, $campaign);

        return new JsonResponse(['backups' => $this->storage->getPlayCampaignBackups($campaignId)]);
    }

    public function restorePlayCampaignBackup(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $this->auth->requirePlayCampaignOwner($request, $campaign);

        $backupId = $parameters['backup_id'] ?? '';
        $backup = $this->storage->restorePlayCampaignBackup($campaignId, $backupId);
        if ($backup === null) {
            return new JsonResponse(['error' => 'backup not found'], 404);
        }

        return new JsonResponse($backup, 200);
    }

    public function appendPlayCampaignReplayEvent(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $this->auth->requirePlayCampaignMemberOrOwner($request, $campaign);

        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body)) {
            return HttpHelper::error('invalid json');
        }
        if (!isset($body['event_id']) || !is_string($body['event_id']) || $body['event_id'] === '') {
            return HttpHelper::error('invalid event_id');
        }
        if (!isset($body['text']) || !is_string($body['text']) || $body['text'] === '') {
            return HttpHelper::error('invalid text');
        }
        if (!isset($body['kind']) || !is_string($body['kind']) || $body['kind'] !== 'append') {
            return HttpHelper::error('invalid kind');
        }

        $event = $this->storage->createPlayCampaignReplayEvent($campaignId, $body['event_id'], $body['kind'], $body['text']);
        if ($event === null) {
            return new JsonResponse(['error' => 'event already exists'], 409);
        }

        return new JsonResponse($event, 201);
    }

    public function getPlayCampaignReplay(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $this->auth->requirePlayCampaignMemberOrOwner($request, $campaign);

        return new JsonResponse($this->storage->getPlayCampaignReplayState($campaignId));
    }

    public function checkPlayCampaignReplay(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $this->auth->requirePlayCampaignMemberOrOwner($request, $campaign);

        return new JsonResponse($this->storage->getPlayCampaignReplayState($campaignId));
    }

    public function setPlayCampaignRngSeed(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $this->auth->requirePlayCampaignOwner($request, $campaign);

        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body) || !isset($body['seed']) || !is_string($body['seed']) || $body['seed'] === '') {
            return HttpHelper::error('invalid seed');
        }

        if ($this->storage->getPlayCampaignRngSeed($campaignId) !== null) {
            return new JsonResponse(['error' => 'seed already configured'], 409);
        }

        if (!$this->storage->setPlayCampaignRngSeed($campaignId, $body['seed'])) {
            return new JsonResponse(['error' => 'seed already configured'], 409);
        }

        return new JsonResponse([
            'seed' => $body['seed'],
            'rolls' => [],
        ]);
    }

    public function appendPlayCampaignRngRoll(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $this->auth->requirePlayCampaignMemberOrOwner($request, $campaign);

        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body)) {
            return HttpHelper::error('invalid json');
        }
        if (!isset($body['roll_id']) || !is_string($body['roll_id']) || $body['roll_id'] === '') {
            return HttpHelper::error('invalid roll_id');
        }
        if (!isset($body['sides']) || !is_int($body['sides']) || $body['sides'] < 2 || $body['sides'] > 100) {
            return HttpHelper::error('invalid sides');
        }

        $seed = $this->storage->getPlayCampaignRngSeed($campaignId);
        if ($seed === null) {
            return new JsonResponse(['error' => 'seed not configured'], 409);
        }

        $record = $this->storage->appendPlayCampaignRngRoll($campaignId, $body['roll_id'], $body['sides'], $seed);
        if (isset($record['error'])) {
            return new JsonResponse(['error' => 'roll_id already exists'], 409);
        }

        return new JsonResponse($record, 201);
    }

    public function getPlayCampaignRngLedger(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $this->auth->requirePlayCampaignMemberOrOwner($request, $campaign);

        $seed = $this->storage->getPlayCampaignRngSeed($campaignId);

        return new JsonResponse([
            'seed' => $seed ?? '',
            'rolls' => $this->storage->getPlayCampaignRngRolls($campaignId),
        ]);
    }

    public function createPlayCampaignModerationReport(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $this->auth->requirePlayCampaignMemberOrOwner($request, $campaign);

        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body)) {
            return HttpHelper::error('invalid json');
        }
        if (!isset($body['report_id']) || !is_string($body['report_id']) || $body['report_id'] === '') {
            return HttpHelper::error('invalid report_id');
        }
        if (!isset($body['target_id']) || !is_string($body['target_id']) || $body['target_id'] === '') {
            return HttpHelper::error('invalid target_id');
        }
        if (!isset($body['reason']) || !is_string($body['reason']) || $body['reason'] === '') {
            return HttpHelper::error('invalid reason');
        }

        $report = $this->storage->createPlayCampaignModerationReport($campaignId, $body['report_id'], $body['target_id'], $body['reason'], $user['username']);
        if ($report === false) {
            return new JsonResponse(['error' => 'report already exists'], 409);
        }

        return new JsonResponse($report, 201);
    }

    public function getPlayCampaignModerationReports(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $this->auth->requirePlayCampaignMemberOrOwner($request, $campaign);

        return new JsonResponse(['reports' => $this->storage->getPlayCampaignModerationReports($campaignId)]);
    }

    public function resolvePlayCampaignModerationReport(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $this->auth->requirePlayCampaignOwner($request, $campaign);

        $reportId = $parameters['report_id'] ?? '';
        $report = $this->storage->getPlayCampaignModerationReport($campaignId, $reportId);
        if ($report === null) {
            return new JsonResponse(['error' => 'report not found'], 404);
        }

        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body)) {
            return HttpHelper::error('invalid json');
        }
        if (!isset($body['action']) || !is_string($body['action']) || ($body['action'] !== 'allow' && $body['action'] !== 'remove')) {
            return HttpHelper::error('invalid action');
        }
        if (!isset($body['note']) || !is_string($body['note']) || $body['note'] === '') {
            return HttpHelper::error('invalid note');
        }

        $result = $this->storage->resolvePlayCampaignModerationReport($campaignId, $reportId, $body['action'], $body['note'], $user['username']);
        if ($result === false) {
            return new JsonResponse(['error' => 'report not found'], 404);
        }
        if (is_array($result) && isset($result['error'])) {
            return new JsonResponse(['error' => 'report already resolved'], 409);
        }

        return new JsonResponse($result, 200);
    }

    public function replacePlayCampaignSafetyBoundaries(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        if ($campaign['owner'] !== $user['username']) {
            return new JsonResponse(['error' => 'forbidden'], 403);
        }

        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body) || !array_key_exists('blocked_tags', $body)) {
            return HttpHelper::error('invalid blocked_tags');
        }

        $tags = $this->validateNonemptyUniqueStringArray($body['blocked_tags']);
        if ($tags === null) {
            return HttpHelper::error('invalid blocked_tags');
        }

        return new JsonResponse($this->storage->setPlayCampaignSafetyBoundaries($campaignId, $tags), 200);
    }

    public function getPlayCampaignSafetyBoundaries(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $this->auth->requirePlayCampaignMemberOrOwner($request, $campaign);

        return new JsonResponse($this->storage->getPlayCampaignSafetyBoundaries($campaignId));
    }

    public function submitPlayCampaignSafetyCheck(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $this->auth->requirePlayCampaignMemberOrOwner($request, $campaign);

        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body)) {
            return HttpHelper::error('invalid json');
        }

        if (!isset($body['event_id']) || !is_string($body['event_id']) || $body['event_id'] === '') {
            return HttpHelper::error('invalid event_id');
        }
        if (!isset($body['text']) || !is_string($body['text']) || $body['text'] === '') {
            return HttpHelper::error('invalid text');
        }
        if (!isset($body['kind']) || !is_string($body['kind']) || ($body['kind'] !== 'narration' && $body['kind'] !== 'chat')) {
            return HttpHelper::error('invalid kind');
        }
        if (!isset($body['tags']) || !is_array($body['tags'])) {
            return HttpHelper::error('invalid tags');
        }
        $tags = $this->validateNonemptyUniqueStringArray($body['tags']);
        if ($tags === null) {
            return HttpHelper::error('invalid tags');
        }

        if ($this->storage->playCampaignSafetyEventExists($campaignId, $body['event_id'])) {
            return new JsonResponse(['error' => 'event_id already exists'], 409);
        }

        $blocked = $this->storage->getPlayCampaignSafetyBoundaries($campaignId)['blocked_tags'] ?? [];
        foreach ($tags as $tag) {
            if (in_array($tag, $blocked, true)) {
                return new JsonResponse(['error' => 'tag blocked'], 409);
            }
        }

        $result = $this->storage->createPlayCampaignSafetyEvent($campaignId, $body['event_id'], $body['kind'], $body['text'], $tags);

        return new JsonResponse($result, 201);
    }

    public function getPlayCampaignSafetyEvents(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $this->auth->requirePlayCampaignMemberOrOwner($request, $campaign);

        return new JsonResponse(['events' => $this->storage->getPlayCampaignSafetyEvents($campaignId)]);
    }

    public function seedPlayCampaignFixture(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        if ($campaign['owner'] !== $user['username']) {
            return new JsonResponse(['error' => 'forbidden'], 403);
        }

        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body) || !array_key_exists('fixture_id', $body) || !is_string($body['fixture_id']) || $body['fixture_id'] !== 'canonical-v1') {
            return HttpHelper::error('invalid fixture_id');
        }

        $existing = $this->storage->getPlayCampaignFixture($campaignId);
        if ($existing !== null) {
            return new JsonResponse($existing, 200);
        }

        $fixture = $this->storage->createPlayCampaignFixture($campaignId);

        return new JsonResponse($fixture, 201);
    }

    public function getPlayCampaignFixtureState(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $this->auth->requirePlayCampaignMemberOrOwner($request, $campaign);

        $fixture = $this->storage->getPlayCampaignFixture($campaignId);
        if ($fixture === null) {
            return new JsonResponse(['error' => 'fixture not found'], 404);
        }

        return new JsonResponse($fixture);
    }

    public function createPlayCampaignSpectator(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);
        $this->auth->requireRole($user, 'dm');

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }
        if ($campaign['owner'] !== $user['username']) {
            return new JsonResponse(['error' => 'forbidden'], 403);
        }

        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body) || !isset($body['spectator_id']) || !is_string($body['spectator_id']) || $body['spectator_id'] === '') {
            return HttpHelper::error('invalid spectator_id');
        }

        $spectatorId = $body['spectator_id'];
        if (!$this->storage->createPlayCampaignSpectator($spectatorId, $campaignId)) {
            return new JsonResponse(['error' => 'spectator already exists'], 409);
        }

        return new JsonResponse([
            'spectator_id' => $spectatorId,
            'token' => 'spectator-' . $spectatorId,
        ], 201);
    }

    public function getPlayCampaignSpectatorView(Request $request, array $parameters): JsonResponse
    {
        $auth = $request->headers->get('Authorization', '');
        if (str_starts_with($auth, 'Bearer session-')) {
            return new JsonResponse(['error' => 'forbidden'], 403);
        }
        if (!str_starts_with($auth, 'Bearer spectator-')) {
            return new JsonResponse(['error' => 'unauthorized'], 401);
        }

        $spectatorId = substr($auth, 17);
        if ($spectatorId === '') {
            return new JsonResponse(['error' => 'unauthorized'], 401);
        }

        $ticketCampaignId = $this->storage->getPlayCampaignSpectatorCampaign($spectatorId);
        if ($ticketCampaignId === null) {
            return new JsonResponse(['error' => 'unauthorized'], 401);
        }

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        if ($ticketCampaignId !== $campaignId) {
            return new JsonResponse(['error' => 'forbidden'], 403);
        }

        $partySize = $this->storage->getPlayCampaignMemberCount($campaignId);
        $document = $this->storage->getPlayCampaignDocument($campaignId);

        return new JsonResponse([
            'campaign_id' => $campaign['id'],
            'name' => $campaign['name'],
            'status' => $campaign['status'],
            'party_size' => $partySize,
            'story' => $document['story'],
        ]);
    }

    public function createPlayCampaignFeedEvent(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $this->auth->requirePlayCampaignMemberOrOwner($request, $campaign);

        $body = HttpHelper::parseJsonBody($request);
        if (!is_array($body)) {
            return HttpHelper::error('invalid json');
        }
        if (!isset($body['event_id']) || !is_string($body['event_id']) || $body['event_id'] === '') {
            return HttpHelper::error('invalid event_id');
        }
        if (!isset($body['text']) || !is_string($body['text']) || $body['text'] === '') {
            return HttpHelper::error('invalid text');
        }

        $event = $this->storage->createPlayCampaignFeedEvent($campaignId, $body['event_id'], $body['text']);
        if ($event === null) {
            return new JsonResponse(['error' => 'event_id already exists'], 409);
        }

        return new JsonResponse($event, 201);
    }

    public function getPlayCampaignEventFeed(Request $request, array $parameters): JsonResponse
    {
        $user = $this->auth->requireUser($request);

        $campaignId = $parameters['id'] ?? '';
        $campaign = $this->storage->getPlayCampaign($campaignId);
        if ($campaign === null) {
            return new JsonResponse(['error' => 'campaign not found'], 404);
        }

        $this->auth->requirePlayCampaignMemberOrOwner($request, $campaign);

        $cursor = 0;
        $cursorRaw = $request->query->get('cursor');
        if ($cursorRaw !== null) {
            $cursor = filter_var($cursorRaw, FILTER_VALIDATE_INT);
            if ($cursor === false || $cursor < 0) {
                return HttpHelper::error('invalid cursor');
            }
        }

        $limit = 2;
        $limitRaw = $request->query->get('limit');
        if ($limitRaw !== null) {
            $limit = filter_var($limitRaw, FILTER_VALIDATE_INT);
            if ($limit === false || $limit < 1 || $limit > 3) {
                return HttpHelper::error('invalid limit');
            }
        }

        return new JsonResponse($this->storage->getPlayCampaignFeedEvents($campaignId, $cursor, $limit));
    }

    private function validateNonemptyUniqueStringArray(mixed $value): ?array
    {
        if (!is_array($value) || count($value) === 0) {
            return null;
        }

        $result = [];
        $seen = [];
        foreach ($value as $item) {
            if (!is_string($item) || trim($item) === '') {
                return null;
            }
            if (isset($seen[$item])) {
                return null;
            }
            $seen[$item] = true;
            $result[] = $item;
        }

        return $result;
    }
}
