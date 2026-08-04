<?php

declare(strict_types=1);

namespace App\Routes;

use App\Http\Json;
use App\Rules\Validation;
use App\Storage\CompendiumRepository;
use App\Storage\Database;
use Psr\Http\Message\ResponseInterface as Response;
use Psr\Http\Message\ServerRequestInterface as Request;
use Slim\App;

/** Monster and item compendium entries: create-once, slug-addressed records. */
final class CompendiumRoutes
{
    public static function register(App $app, string $dbFile): void
    {
        $app->post('/v1/compendium/monsters', function (Request $request, Response $response) use ($dbFile) {
            $repo = new CompendiumRepository(Database::connect($dbFile));
            $body = Json::parseBody($request);
            $slug = $body['slug'] ?? null;
            $name = $body['name'] ?? null;
            $cr = $body['cr'] ?? null;
            $armorClass = $body['armor_class'] ?? null;
            $hitPoints = $body['hit_points'] ?? null;
            $tags = $body['tags'] ?? [];

            if (!Validation::isSlug($slug)) {
                return Json::response($response, ['error' => 'invalid slug'], 400);
            }
            if (!is_string($name) || $name === '') {
                return Json::response($response, ['error' => 'invalid name'], 400);
            }
            if (!is_string($cr) || $cr === '') {
                return Json::response($response, ['error' => 'invalid cr'], 400);
            }
            if (!is_int($armorClass) || $armorClass < 0) {
                return Json::response($response, ['error' => 'invalid armor_class'], 400);
            }
            if (!is_int($hitPoints) || $hitPoints < 0) {
                return Json::response($response, ['error' => 'invalid hit_points'], 400);
            }
            if (!is_array($tags)) {
                return Json::response($response, ['error' => 'invalid tags'], 400);
            }
            foreach ($tags as $tag) {
                if (!is_string($tag)) {
                    return Json::response($response, ['error' => 'invalid tags'], 400);
                }
            }

            if ($repo->fetch('monsters', $slug) !== null) {
                return Json::response($response, ['error' => 'slug already exists'], 409);
            }

            $monster = [
                'slug' => $slug,
                'name' => $name,
                'cr' => $cr,
                'armor_class' => $armorClass,
                'hit_points' => $hitPoints,
                'tags' => array_values($tags),
            ];

            $repo->insert('monsters', $slug, $monster);

            return Json::response($response, [
                'slug' => $slug,
                'name' => $name,
                'cr' => $cr,
                'armor_class' => $armorClass,
                'hit_points' => $hitPoints,
            ], 201);
        });

        $app->get('/v1/compendium/monsters/{slug}', function (Request $request, Response $response, array $args) use ($dbFile) {
            $repo = new CompendiumRepository(Database::connect($dbFile));
            $monster = $repo->fetch('monsters', $args['slug']);
            if ($monster === null) {
                return Json::response($response, ['error' => 'monster not found'], 404);
            }
            return Json::response($response, $monster);
        });

        $app->post('/v1/compendium/items', function (Request $request, Response $response) use ($dbFile) {
            $repo = new CompendiumRepository(Database::connect($dbFile));
            $body = Json::parseBody($request);
            $slug = $body['slug'] ?? null;
            $name = $body['name'] ?? null;
            $type = $body['type'] ?? null;
            $rarity = $body['rarity'] ?? null;
            $costGp = $body['cost_gp'] ?? null;

            if (!Validation::isSlug($slug)) {
                return Json::response($response, ['error' => 'invalid slug'], 400);
            }
            if (!is_string($name) || $name === '') {
                return Json::response($response, ['error' => 'invalid name'], 400);
            }
            if (!is_string($type) || $type === '') {
                return Json::response($response, ['error' => 'invalid type'], 400);
            }
            if (!is_string($rarity) || $rarity === '') {
                return Json::response($response, ['error' => 'invalid rarity'], 400);
            }
            if (!is_numeric($costGp) || $costGp < 0) {
                return Json::response($response, ['error' => 'invalid cost_gp'], 400);
            }

            if ($repo->fetch('items', $slug) !== null) {
                return Json::response($response, ['error' => 'slug already exists'], 409);
            }

            $item = [
                'slug' => $slug,
                'name' => $name,
                'type' => $type,
                'rarity' => $rarity,
                'cost_gp' => $costGp,
            ];

            $repo->insert('items', $slug, $item);

            return Json::response($response, $item, 201);
        });

        $app->get('/v1/compendium/items/{slug}', function (Request $request, Response $response, array $args) use ($dbFile) {
            $repo = new CompendiumRepository(Database::connect($dbFile));
            $item = $repo->fetch('items', $args['slug']);
            if ($item === null) {
                return Json::response($response, ['error' => 'item not found'], 404);
            }
            return Json::response($response, $item);
        });
    }
}
