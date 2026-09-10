<?php

declare(strict_types=1);

use Psr\Http\Message\ResponseInterface as Response;
use Psr\Http\Message\ServerRequestInterface as Request;
use Slim\App;

/**
 * Campaign-management endpoints: campaigns, characters, events, quests, factions,
 * NPCs, relationships, inventory, equipment, audit, export, and state reads.
 */
final class CampaignHandler
{
    use HasCampaign;

    public function __construct(
        private GameDatabase $db,
    ) {}

    public function register(App $app): void
    {
        $app->post('/v1/campaigns', $this->createCampaign(...));
        $app->post('/v1/campaigns/{id}/characters', $this->addCharacter(...));
        $app->post('/v1/campaigns/{id}/events', $this->addEvent(...));
        $app->get('/v1/campaigns/{id}/quests/summary', $this->getQuestSummary(...));
        $app->post('/v1/campaigns/{id}/quests/{quest_id}/progress', $this->updateQuestProgress(...));
        $app->post('/v1/campaigns/{id}/quests', $this->createQuest(...));
        $app->post('/v1/campaigns/{id}/factions', $this->createFaction(...));
        $app->post('/v1/campaigns/{id}/npcs', $this->createNpc(...));
        $app->get('/v1/campaigns/{id}/relationships', $this->getRelationships(...));
        $app->get('/v1/campaigns/{id}/state', $this->getState(...));
        $app->get('/v1/campaigns/{id}/audit', $this->getAudit(...));
        $app->get('/v1/campaigns/{id}/export', $this->getExport(...));
        $app->get('/v1/campaigns/{id}/inventory/summary', $this->getInventorySummary(...));
        $app->post('/v1/campaigns/{id}/inventory', $this->addInventoryItem(...));
        $app->post('/v1/campaigns/{id}/characters/{character_id}/equipment', $this->assignEquipment(...));
    }

    private function createCampaign(Request $request, Response $response): Response
    {
        $body = $request->getParsedBody() ?? [];

        if (!isset($body['id']) || (!is_string($body['id']) && !is_numeric($body['id']))
            || !isset($body['name']) || (!is_string($body['name']) && !is_numeric($body['name']))
            || !isset($body['dm']) || (!is_string($body['dm']) && !is_numeric($body['dm']))) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $id = (string) $body['id'];
        $name = (string) $body['name'];
        $dm = (string) $body['dm'];
        if ($id === '' || $name === '' || $dm === '') {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }
        if ($this->db->findCampaign($id) !== null) {
            return respondJson($response, 409, ['error' => 'campaign id already exists']);
        }

        $campaign = ['id' => $id, 'name' => $name, 'dm' => $dm];
        $this->db->createCampaign($campaign);

        return respondJson($response, 201, $campaign);
    }

    private function addCharacter(Request $request, Response $response, array $args): Response
    {
        $campaignId = (string) $args['id'];
        $campaign = $this->requireCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $body = $request->getParsedBody() ?? [];

        if (!isset($body['id']) || (!is_string($body['id']) && !is_numeric($body['id']))
            || !isset($body['name']) || (!is_string($body['name']) && !is_numeric($body['name']))
            || !isset($body['level']) || !is_numeric($body['level'])
            || !isset($body['class']) || (!is_string($body['class']) && !is_numeric($body['class']))) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $id = (string) $body['id'];
        $name = (string) $body['name'];
        $level = (int) $body['level'];
        $class = (string) $body['class'];
        if ($id === '' || $name === '' || $class === '' || $level < 1 || $level > 20) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }
        if ($this->db->findCampaignCharacter($id) !== null) {
            return respondJson($response, 409, ['error' => 'character id already exists']);
        }

        $character = ['id' => $id, 'campaign_id' => $campaignId, 'name' => $name, 'level' => $level, 'class' => $class];
        $this->db->createCampaignCharacter($character);

        return respondJson($response, 201, [
            'id' => $id,
            'name' => $name,
            'level' => $level,
            'class' => $class,
        ]);
    }

    private function addEvent(Request $request, Response $response, array $args): Response
    {
        $campaignId = (string) $args['id'];
        $campaign = $this->requireCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $body = $request->getParsedBody() ?? [];

        if (!isset($body['id']) || (!is_string($body['id']) && !is_numeric($body['id']))
            || !isset($body['kind']) || (!is_string($body['kind']) && !is_numeric($body['kind']))
            || !isset($body['summary']) || (!is_string($body['summary']) && !is_numeric($body['summary']))) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $id = (string) $body['id'];
        $kind = (string) $body['kind'];
        $summary = (string) $body['summary'];
        if ($id === '' || $kind === '' || $summary === '') {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }
        if ($this->db->findCampaignEvent($id) !== null) {
            return respondJson($response, 409, ['error' => 'event id already exists']);
        }

        $event = ['id' => $id, 'campaign_id' => $campaignId, 'kind' => $kind, 'summary' => $summary];
        $this->db->createCampaignEvent($event);

        return respondJson($response, 201, ['id' => $id, 'kind' => $kind]);
    }

    private function getState(Request $request, Response $response, array $args): Response
    {
        $campaignId = (string) $args['id'];
        $campaign = $this->requireCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        return respondJson($response, 200, [
            'id' => $campaign['id'],
            'name' => $campaign['name'],
            'dm' => $campaign['dm'],
            'characters' => $this->db->findCampaignCharacters($campaignId),
            'log_count' => $this->db->countCampaignEvents($campaignId),
        ]);
    }

    private function createQuest(Request $request, Response $response, array $args): Response
    {
        $campaignId = (string) $args['id'];
        $campaign = $this->requireCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $body = $request->getParsedBody() ?? [];

        if (!isset($body['id']) || (!is_string($body['id']) && !is_numeric($body['id']))
            || !isset($body['title']) || (!is_string($body['title']) && !is_numeric($body['title']))
            || !isset($body['status']) || (!is_string($body['status']) && !is_numeric($body['status']))
            || !isset($body['milestones']) || !is_array($body['milestones'])) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $id = (string) $body['id'];
        $title = (string) $body['title'];
        $status = (string) $body['status'];
        if ($id === '' || $title === '' || !in_array($status, ['active', 'completed', 'blocked'], true)) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $milestones = [];
        foreach ($body['milestones'] as $m) {
            if (!is_string($m) && !is_numeric($m) || (string) $m === '') {
                return respondJson($response, 400, ['error' => 'invalid request']);
            }
            $milestones[] = (string) $m;
        }

        if ($this->db->findQuest($id) !== null) {
            return respondJson($response, 409, ['error' => 'quest id already exists']);
        }

        $quest = [
            'id' => $id,
            'campaign_id' => $campaignId,
            'title' => $title,
            'status' => $status,
            'milestones' => $milestones,
            'completed' => [],
        ];
        $this->db->createQuest($quest);

        return respondJson($response, 201, [
            'id' => $id,
            'title' => $title,
            'status' => $status,
            'milestones_total' => count($milestones),
            'milestones_done' => 0,
        ]);
    }

    private function updateQuestProgress(Request $request, Response $response, array $args): Response
    {
        $campaignId = (string) $args['id'];
        $questId = (string) $args['quest_id'];

        $campaign = $this->requireCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $quest = $this->db->findQuest($questId);
        if ($quest === null || $quest['campaign_id'] !== $campaignId) {
            return respondJson($response, 404, ['error' => 'quest not found']);
        }

        $body = $request->getParsedBody() ?? [];
        if (!isset($body['completed']) || !is_array($body['completed'])) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $completed = [];
        foreach ($body['completed'] as $c) {
            if (!is_string($c) && !is_numeric($c) || (string) $c === '') {
                return respondJson($response, 400, ['error' => 'invalid request']);
            }
            $completed[] = (string) $c;
        }

        $done = array_values(array_unique(array_merge($quest['completed'], array_intersect($completed, $quest['milestones']))));
        $quest['completed'] = $done;
        if (count($done) === count($quest['milestones']) && count($quest['milestones']) > 0) {
            $quest['status'] = 'completed';
        }
        $this->db->updateQuest($quest);

        return respondJson($response, 200, [
            'id' => $questId,
            'status' => $quest['status'],
            'milestones_total' => count($quest['milestones']),
            'milestones_done' => count($done),
        ]);
    }

    private function getQuestSummary(Request $request, Response $response, array $args): Response
    {
        $campaignId = (string) $args['id'];
        $campaign = $this->requireCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $counts = $this->db->countQuestsByStatus($campaignId);
        return respondJson($response, 200, [
            'campaign_id' => $campaignId,
            'active' => $counts['active'],
            'completed' => $counts['completed'],
            'blocked' => $counts['blocked'],
        ]);
    }

    private function createFaction(Request $request, Response $response, array $args): Response
    {
        $campaignId = (string) $args['id'];
        $campaign = $this->requireCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $body = $request->getParsedBody() ?? [];

        if (!isset($body['id']) || (!is_string($body['id']) && !is_numeric($body['id']))
            || !isset($body['name']) || (!is_string($body['name']) && !is_numeric($body['name']))
            || !isset($body['stance']) || (!is_string($body['stance']) && !is_numeric($body['stance']))) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $id = (string) $body['id'];
        $name = (string) $body['name'];
        $stance = (string) $body['stance'];
        if ($id === '' || $name === '' || $stance === '') {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }
        if ($this->db->findFaction($id) !== null) {
            return respondJson($response, 409, ['error' => 'faction id already exists']);
        }

        $faction = ['id' => $id, 'campaign_id' => $campaignId, 'name' => $name, 'stance' => $stance];
        $this->db->createFaction($faction);

        return respondJson($response, 201, ['id' => $id, 'name' => $name, 'stance' => $stance]);
    }

    private function createNpc(Request $request, Response $response, array $args): Response
    {
        $campaignId = (string) $args['id'];
        $campaign = $this->requireCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $body = $request->getParsedBody() ?? [];

        if (!isset($body['id']) || (!is_string($body['id']) && !is_numeric($body['id']))
            || !isset($body['name']) || (!is_string($body['name']) && !is_numeric($body['name']))
            || !isset($body['faction_id']) || (!is_string($body['faction_id']) && !is_numeric($body['faction_id']))
            || !isset($body['disposition']) || !is_numeric($body['disposition'])) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $id = (string) $body['id'];
        $name = (string) $body['name'];
        $factionId = (string) $body['faction_id'];
        $disposition = (int) $body['disposition'];
        if ($id === '' || $name === '' || $factionId === '') {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $faction = $this->db->findFaction($factionId);
        if ($faction === null || $faction['campaign_id'] !== $campaignId) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        if ($this->db->findNpc($id) !== null) {
            return respondJson($response, 409, ['error' => 'npc id already exists']);
        }

        $npc = ['id' => $id, 'campaign_id' => $campaignId, 'name' => $name, 'faction_id' => $factionId, 'disposition' => $disposition];
        $this->db->createNpc($npc);

        return respondJson($response, 201, ['id' => $id, 'name' => $name, 'faction_id' => $factionId, 'disposition' => $disposition]);
    }

    private function getRelationships(Request $request, Response $response, array $args): Response
    {
        $campaignId = (string) $args['id'];
        $campaign = $this->requireCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        return respondJson($response, 200, [
            'campaign_id' => $campaignId,
            'factions' => $this->db->countCampaignFactions($campaignId),
            'npcs' => $this->db->countCampaignNpcs($campaignId),
            'friendly_npcs' => $this->db->countFriendlyCampaignNpcs($campaignId),
        ]);
    }

    private function addInventoryItem(Request $request, Response $response, array $args): Response
    {
        $campaignId = (string) $args['id'];
        $campaign = $this->requireCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $body = $request->getParsedBody() ?? [];
        if (!isset($body['item_slug']) || (!is_string($body['item_slug']) && !is_numeric($body['item_slug']))
            || !isset($body['quantity']) || !is_numeric($body['quantity'])
            || !isset($body['owner']) || (!is_string($body['owner']) && !is_numeric($body['owner']))) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $itemSlug = (string) $body['item_slug'];
        $quantity = (int) $body['quantity'];
        $owner = (string) $body['owner'];
        if ($itemSlug === '' || $owner === '' || $quantity <= 0) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $this->db->addInventoryItem($campaignId, $itemSlug, $quantity, $owner);

        return respondJson($response, 201, [
            'item_slug' => $itemSlug,
            'quantity' => $quantity,
            'owner' => $owner,
        ]);
    }

    private function assignEquipment(Request $request, Response $response, array $args): Response
    {
        $campaignId = (string) $args['id'];
        $characterId = (string) $args['character_id'];

        $campaign = $this->requireCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $character = $this->db->findCampaignCharacter($characterId);
        if ($character === null || $character['campaign_id'] !== $campaignId) {
            return respondJson($response, 404, ['error' => 'character not found']);
        }

        $body = $request->getParsedBody() ?? [];
        if (!isset($body['item_slug']) || (!is_string($body['item_slug']) && !is_numeric($body['item_slug']))
            || !isset($body['quantity']) || !is_numeric($body['quantity'])) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $itemSlug = (string) $body['item_slug'];
        $quantity = (int) $body['quantity'];
        if ($itemSlug === '' || $quantity <= 0) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $available = $this->db->getPartyInventoryItemQuantity($campaignId, $itemSlug);
        if ($available < $quantity) {
            return respondJson($response, 400, ['error' => 'insufficient quantity']);
        }

        $this->db->reducePartyInventoryQuantity($campaignId, $itemSlug, $quantity);
        $this->db->addEquipment($campaignId, $characterId, $itemSlug, $quantity);

        return respondJson($response, 200, [
            'character_id' => $characterId,
            'item_slug' => $itemSlug,
            'quantity' => $quantity,
        ]);
    }

    private function getAudit(Request $request, Response $response, array $args): Response
    {
        $campaignId = (string) $args['id'];
        $campaign = $this->requireCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        return respondJson($response, 200, [
            'campaign_id' => $campaignId,
            'events' => $this->db->countCampaignEvents($campaignId),
            'quests' => $this->db->countCampaignQuests($campaignId),
            'npcs' => $this->db->countCampaignNpcs($campaignId),
            'sessions' => $this->db->countCampaignSessions($campaignId),
        ]);
    }

    private function getExport(Request $request, Response $response, array $args): Response
    {
        $campaignId = (string) $args['id'];
        $campaign = $this->requireCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        return respondJson($response, 200, [
            'campaign_id' => $campaignId,
            'name' => $campaign['name'],
            'characters' => $this->db->countCampaignCharacters($campaignId),
            'quests' => $this->db->countCampaignQuests($campaignId),
            'npcs' => $this->db->countCampaignNpcs($campaignId),
            'inventory_items' => $this->db->countCampaignInventoryItems($campaignId),
            'sessions' => $this->db->countCampaignSessions($campaignId),
            'schema_version' => GameDatabase::SCHEMA_VERSION,
        ]);
    }

    private function getInventorySummary(Request $request, Response $response, array $args): Response
    {
        $campaignId = (string) $args['id'];
        $campaign = $this->requireCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        return respondJson($response, 200, [
            'campaign_id' => $campaignId,
            'party_items' => $this->db->countPartyInventoryItemTypes($campaignId),
            'assigned_items' => $this->db->countAssignedEquipmentItemTypes($campaignId),
            'healing_potions_available' => $this->db->getPartyInventoryItemQuantity($campaignId, 'healing-potion'),
        ]);
    }
}
