<?php

declare(strict_types=1);

/**
 * Monster and item compendium entries.
 */

function createMonster(array $input): array
{
    $required = ['slug', 'name', 'cr', 'armor_class', 'hit_points'];
    foreach ($required as $key) {
        if (!array_key_exists($key, $input)) {
            sendError(400, 'missing fields');
        }
    }

    $slug = $input['slug'];
    $name = $input['name'];
    $cr = $input['cr'];
    if (!is_string($slug) || $slug === '' || !is_string($name) || $name === '' || !is_string($cr) || $cr === '') {
        sendError(400, 'invalid fields');
    }

    $armorClass = filter_var($input['armor_class'], FILTER_VALIDATE_INT);
    $hitPoints = filter_var($input['hit_points'], FILTER_VALIDATE_INT);
    if ($armorClass === false || $hitPoints === false) {
        sendError(400, 'invalid fields');
    }

    $tags = [];
    if (array_key_exists('tags', $input)) {
        if (!is_array($input['tags'])) {
            sendError(400, 'invalid tags');
        }
        foreach ($input['tags'] as $tag) {
            if (!is_string($tag)) {
                sendError(400, 'invalid tags');
            }
            $tags[] = $tag;
        }
    }

    if (getMonsterBySlug($slug) !== null) {
        sendError(409, 'slug already exists');
    }

    $stmt = db()->prepare('INSERT INTO monsters (slug, name, cr, armor_class, hit_points, tags_json) VALUES (?, ?, ?, ?, ?, ?)');
    $stmt->execute([$slug, $name, $cr, $armorClass, $hitPoints, json_encode($tags, JSON_UNESCAPED_SLASHES)]);

    return [
        'slug' => $slug,
        'name' => $name,
        'cr' => $cr,
        'armor_class' => $armorClass,
        'hit_points' => $hitPoints,
    ];
}

function getMonsterBySlug(string $slug): ?array
{
    $stmt = db()->prepare('SELECT slug, name, cr, armor_class, hit_points, tags_json FROM monsters WHERE slug = ?');
    $stmt->execute([$slug]);
    $row = $stmt->fetch(PDO::FETCH_ASSOC);
    if ($row === false) {
        return null;
    }
    return [
        'slug' => $row['slug'],
        'name' => $row['name'],
        'cr' => $row['cr'],
        'armor_class' => (int) $row['armor_class'],
        'hit_points' => (int) $row['hit_points'],
        'tags' => json_decode($row['tags_json'], true),
    ];
}

function createItem(array $input): array
{
    $required = ['slug', 'name', 'type', 'rarity', 'cost_gp'];
    foreach ($required as $key) {
        if (!array_key_exists($key, $input)) {
            sendError(400, 'missing fields');
        }
    }

    $slug = $input['slug'];
    $name = $input['name'];
    $type = $input['type'];
    $rarity = $input['rarity'];
    if (!is_string($slug) || $slug === '' || !is_string($name) || $name === '' || !is_string($type) || $type === '' || !is_string($rarity) || $rarity === '') {
        sendError(400, 'invalid fields');
    }

    $costGp = filter_var($input['cost_gp'], FILTER_VALIDATE_INT);
    if ($costGp === false) {
        sendError(400, 'invalid fields');
    }

    if (getItemBySlug($slug) !== null) {
        sendError(409, 'slug already exists');
    }

    $stmt = db()->prepare('INSERT INTO items (slug, name, type, rarity, cost_gp) VALUES (?, ?, ?, ?, ?)');
    $stmt->execute([$slug, $name, $type, $rarity, $costGp]);

    return [
        'slug' => $slug,
        'name' => $name,
        'type' => $type,
        'rarity' => $rarity,
        'cost_gp' => $costGp,
    ];
}

function getItemBySlug(string $slug): ?array
{
    $stmt = db()->prepare('SELECT slug, name, type, rarity, cost_gp FROM items WHERE slug = ?');
    $stmt->execute([$slug]);
    $row = $stmt->fetch(PDO::FETCH_ASSOC);
    if ($row === false) {
        return null;
    }
    return [
        'slug' => $row['slug'],
        'name' => $row['name'],
        'type' => $row['type'],
        'rarity' => $row['rarity'],
        'cost_gp' => (int) $row['cost_gp'],
    ];
}
