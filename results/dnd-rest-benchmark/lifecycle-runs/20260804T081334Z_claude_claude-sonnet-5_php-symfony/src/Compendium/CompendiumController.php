<?php

namespace App\Compendium;

use App\Storage\Database;
use App\Support\Json;
use App\Support\Validators;
use PDO;
use Symfony\Component\HttpFoundation\JsonResponse;

/** Handlers for the monster/item reference-data endpoints (/v1/compendium/*). */
final class CompendiumController
{
    public function createMonster(array $body): JsonResponse
    {
        $slug = $body['slug'] ?? null;
        $name = $body['name'] ?? null;
        $cr = $body['cr'] ?? null;
        $armorClass = $body['armor_class'] ?? null;
        $hitPoints = $body['hit_points'] ?? null;
        $tags = $body['tags'] ?? [];

        if (!Validators::isValidSlug($slug) || !is_string($name) || $name === ''
            || !is_string($cr) || $cr === ''
            || !Validators::isValidInt($armorClass) || !Validators::isValidInt($hitPoints)
            || !is_array($tags)) {
            return Json::error('invalid request');
        }
        foreach ($tags as $tag) {
            if (!is_string($tag)) {
                return Json::error('invalid tags');
            }
        }

        $armorClass = (int) $armorClass;
        $hitPoints = (int) $hitPoints;

        $db = Database::connection();
        $stmt = $db->prepare('SELECT slug FROM monsters WHERE slug = ?');
        $stmt->execute([$slug]);
        if ($stmt->fetchColumn() !== false) {
            return Json::error('slug already exists', 409);
        }

        $insert = $db->prepare('INSERT INTO monsters (slug, name, cr, armor_class, hit_points, tags) VALUES (?, ?, ?, ?, ?, ?)');
        $insert->execute([$slug, $name, $cr, $armorClass, $hitPoints, json_encode(array_values($tags))]);

        return new JsonResponse([
            'slug' => $slug,
            'name' => $name,
            'cr' => $cr,
            'armor_class' => $armorClass,
            'hit_points' => $hitPoints,
        ], 201);
    }

    public function getMonster(string $slug): JsonResponse
    {
        $db = Database::connection();
        $stmt = $db->prepare('SELECT slug, name, cr, armor_class, hit_points, tags FROM monsters WHERE slug = ?');
        $stmt->execute([$slug]);
        $row = $stmt->fetch(PDO::FETCH_ASSOC);
        if ($row === false) {
            return Json::error('monster not found', 404);
        }

        return new JsonResponse([
            'slug' => $row['slug'],
            'name' => $row['name'],
            'cr' => $row['cr'],
            'armor_class' => (int) $row['armor_class'],
            'hit_points' => (int) $row['hit_points'],
            'tags' => json_decode($row['tags'], true),
        ]);
    }

    public function createItem(array $body): JsonResponse
    {
        $slug = $body['slug'] ?? null;
        $name = $body['name'] ?? null;
        $type = $body['type'] ?? null;
        $rarity = $body['rarity'] ?? null;
        $costGp = $body['cost_gp'] ?? null;

        if (!Validators::isValidSlug($slug) || !is_string($name) || $name === ''
            || !is_string($type) || $type === ''
            || !is_string($rarity) || $rarity === ''
            || !Validators::isValidInt($costGp)) {
            return Json::error('invalid request');
        }

        $costGp = (int) $costGp;

        $db = Database::connection();
        $stmt = $db->prepare('SELECT slug FROM items WHERE slug = ?');
        $stmt->execute([$slug]);
        if ($stmt->fetchColumn() !== false) {
            return Json::error('slug already exists', 409);
        }

        $insert = $db->prepare('INSERT INTO items (slug, name, type, rarity, cost_gp) VALUES (?, ?, ?, ?, ?)');
        $insert->execute([$slug, $name, $type, $rarity, $costGp]);

        return new JsonResponse([
            'slug' => $slug,
            'name' => $name,
            'type' => $type,
            'rarity' => $rarity,
            'cost_gp' => $costGp,
        ], 201);
    }

    public function getItem(string $slug): JsonResponse
    {
        $db = Database::connection();
        $stmt = $db->prepare('SELECT slug, name, type, rarity, cost_gp FROM items WHERE slug = ?');
        $stmt->execute([$slug]);
        $row = $stmt->fetch(PDO::FETCH_ASSOC);
        if ($row === false) {
            return Json::error('item not found', 404);
        }

        return new JsonResponse([
            'slug' => $row['slug'],
            'name' => $row['name'],
            'type' => $row['type'],
            'rarity' => $row['rarity'],
            'cost_gp' => (int) $row['cost_gp'],
        ]);
    }
}
