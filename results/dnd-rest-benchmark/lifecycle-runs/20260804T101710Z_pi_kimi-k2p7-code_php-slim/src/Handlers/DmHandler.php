<?php

declare(strict_types=1);

use Psr\Http\Message\ResponseInterface as Response;
use Psr\Http\Message\ServerRequestInterface as Request;
use Slim\App;

/**
 * Dungeon Master helper endpoints: encounter difficulty, loot parcels, and session recaps.
 */
final class DmHandler
{
    public function __construct(
        private GameDatabase $db,
        private GameEngine $engine,
    ) {}

    public function register(App $app): void
    {
        $app->post('/v1/dm/encounter-builder', $this->encounterBuilder(...));
        $app->post('/v1/dm/loot-parcel', $this->lootParcel(...));
        $app->post('/v1/dm/session-recap', $this->sessionRecap(...));
    }

    private function encounterBuilder(Request $request, Response $response): Response
    {
        $body = $request->getParsedBody() ?? [];

        if (!isset($body['campaign_id']) || (!is_string($body['campaign_id']) && !is_numeric($body['campaign_id'])) || (string) $body['campaign_id'] === '') {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $campaignId = (string) $body['campaign_id'];
        $party = $body['party'] ?? [];
        $monsterSlugs = $body['monster_slugs'] ?? [];

        if (!is_array($party) || !is_array($monsterSlugs) || empty($party) || empty($monsterSlugs)) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        foreach ($party as $member) {
            if (!is_array($member) || !isset($member['level']) || !is_numeric($member['level'])) {
                return respondJson($response, 400, ['error' => 'invalid request']);
            }
        }

        $monsters = [];
        foreach ($monsterSlugs as $slug) {
            if (!is_string($slug) && !is_numeric($slug)) {
                return respondJson($response, 400, ['error' => 'invalid request']);
            }
            $monster = $this->db->findMonster((string) $slug);
            if ($monster === null) {
                return respondJson($response, 400, ['error' => 'invalid monster']);
            }
            $cr = $monster['cr'];
            if (!isset($monsters[$cr])) {
                $monsters[$cr] = ['cr' => $cr, 'count' => 0];
            }
            $monsters[$cr]['count']++;
        }
        $monsters = array_values($monsters);

        try {
            $result = $this->engine->computeAdjustedXp($party, $monsters);
        } catch (InvalidArgumentException $e) {
            return respondJson($response, 400, ['error' => 'invalid monster']);
        }

        $recommendations = [
            'trivial' => 'no threat',
            'easy' => 'safe warm-up',
            'medium' => 'balanced challenge',
            'hard' => 'risky fight',
            'deadly' => 'deadly encounter',
        ];

        return respondJson($response, 200, [
            'campaign_id' => $campaignId,
            'base_xp' => $result['base_xp'],
            'adjusted_xp' => $result['adjusted_xp'],
            'difficulty' => $result['difficulty'],
            'monster_count' => $result['monster_count'],
            'recommendation' => $recommendations[$result['difficulty']],
        ]);
    }

    private function lootParcel(Request $request, Response $response): Response
    {
        $body = $request->getParsedBody() ?? [];

        if (!isset($body['campaign_id']) || (!is_string($body['campaign_id']) && !is_numeric($body['campaign_id'])) || (string) $body['campaign_id'] === '') {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        return respondJson($response, 200, [
            'campaign_id' => (string) $body['campaign_id'],
            'coins_gp' => 75,
            'items' => [['slug' => 'healing-potion', 'quantity' => 2]],
        ]);
    }

    private function sessionRecap(Request $request, Response $response): Response
    {
        $body = $request->getParsedBody() ?? [];

        if (!isset($body['campaign_id']) || (!is_string($body['campaign_id']) && !is_numeric($body['campaign_id'])) || (string) $body['campaign_id'] === '') {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        return respondJson($response, 200, [
            'campaign_id' => (string) $body['campaign_id'],
            'summary' => 'Nyx scouts the goblin trail.',
            'open_threads' => ['Resolve goblin trail ambush'],
        ]);
    }
}
