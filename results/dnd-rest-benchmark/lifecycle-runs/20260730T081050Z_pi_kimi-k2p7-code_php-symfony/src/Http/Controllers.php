<?php

declare(strict_types=1);

namespace App\Http;

use App\Domain\CharacterRules;
use App\Domain\Dice;
use App\Domain\Encounter;
use App\Domain\Initiative;
use App\Domain\RestRules;
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
    public function __construct(private GameStorage $storage)
    {
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

        $this->storage->addInventoryItem($campaignId, $itemSlug, $quantity, $owner);

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

        $this->storage->addInventoryItem($campaignId, $itemSlug, $quantity, $characterId);

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
            $this->storage->addInventoryItem($campaignId, $updated['item_slug'], 1, 'party');
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
}
