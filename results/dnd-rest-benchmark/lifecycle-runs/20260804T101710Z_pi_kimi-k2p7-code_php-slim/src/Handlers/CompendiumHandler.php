<?php

declare(strict_types=1);

use Psr\Http\Message\ResponseInterface as Response;
use Psr\Http\Message\ServerRequestInterface as Request;
use Slim\App;

/**
 * Compendium endpoints for monsters and items.
 *
 * Monsters are stored with an associated list of tags. The creation response
 * omits tags to match the existing wire format; the read endpoint returns the
 * full record including tags.
 */
final class CompendiumHandler
{
    public function __construct(
        private GameDatabase $db,
    ) {}

    public function register(App $app): void
    {
        $app->post('/v1/compendium/monsters', $this->createMonster(...));
        $app->get('/v1/compendium/monsters/{slug}', $this->getMonster(...));
        $app->post('/v1/compendium/items', $this->createItem(...));
        $app->get('/v1/compendium/items/{slug}', $this->getItem(...));
    }

    private function createMonster(Request $request, Response $response): Response
    {
        $body = $request->getParsedBody() ?? [];

        if (!isset($body['slug']) || !is_string($body['slug']) || $body['slug'] === ''
            || !isset($body['name']) || !is_string($body['name']) || $body['name'] === ''
            || !isset($body['cr']) || !is_string($body['cr']) || $body['cr'] === ''
            || !isset($body['armor_class']) || !is_numeric($body['armor_class'])
            || !isset($body['hit_points']) || !is_numeric($body['hit_points'])) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $slug = $body['slug'];
        if ($this->db->findMonster($slug) !== null) {
            return respondJson($response, 409, ['error' => 'slug already exists']);
        }

        $tags = [];
        if (isset($body['tags'])) {
            if (!is_array($body['tags'])) {
                return respondJson($response, 400, ['error' => 'invalid tags']);
            }
            foreach ($body['tags'] as $tag) {
                if (!is_string($tag)) {
                    return respondJson($response, 400, ['error' => 'invalid tag']);
                }
                $tags[] = $tag;
            }
        }

        $monster = [
            'slug' => $slug,
            'name' => $body['name'],
            'cr' => $body['cr'],
            'armor_class' => (int) $body['armor_class'],
            'hit_points' => (int) $body['hit_points'],
            'tags' => $tags,
        ];
        $this->db->createMonster($monster);

        return respondJson($response, 201, [
            'slug' => $monster['slug'],
            'name' => $monster['name'],
            'cr' => $monster['cr'],
            'armor_class' => $monster['armor_class'],
            'hit_points' => $monster['hit_points'],
        ]);
    }

    private function getMonster(Request $request, Response $response, array $args): Response
    {
        $slug = (string) $args['slug'];
        $monster = $this->db->findMonster($slug);
        if ($monster === null) {
            return respondJson($response, 404, ['error' => 'monster not found']);
        }
        return respondJson($response, 200, $monster);
    }

    private function createItem(Request $request, Response $response): Response
    {
        $body = $request->getParsedBody() ?? [];

        if (!isset($body['slug']) || !is_string($body['slug']) || $body['slug'] === ''
            || !isset($body['name']) || !is_string($body['name']) || $body['name'] === ''
            || !isset($body['type']) || !is_string($body['type']) || $body['type'] === ''
            || !isset($body['rarity']) || !is_string($body['rarity']) || $body['rarity'] === ''
            || !isset($body['cost_gp']) || !is_numeric($body['cost_gp'])) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $slug = $body['slug'];
        if ($this->db->findItem($slug) !== null) {
            return respondJson($response, 409, ['error' => 'slug already exists']);
        }

        $item = [
            'slug' => $slug,
            'name' => $body['name'],
            'type' => $body['type'],
            'rarity' => $body['rarity'],
            'cost_gp' => (int) $body['cost_gp'],
        ];
        $this->db->createItem($item);

        return respondJson($response, 201, $item);
    }

    private function getItem(Request $request, Response $response, array $args): Response
    {
        $slug = (string) $args['slug'];
        $item = $this->db->findItem($slug);
        if ($item === null) {
            return respondJson($response, 404, ['error' => 'item not found']);
        }
        return respondJson($response, 200, $item);
    }
}
