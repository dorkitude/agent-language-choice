<?php
declare(strict_types=1);

// Routes: Compendium (monsters, items)
// ---------------------------------------------------------------------------

if ($method === 'POST' && $path === '/v1/compendium/monsters') {
    $body = read_json_body();
    if ($body === null || !isset($body['slug'], $body['name'], $body['cr'], $body['armor_class'], $body['hit_points'])
        || !is_valid_slug($body['slug']) || !is_string($body['name']) || !is_string($body['cr'])
        || !is_numeric($body['armor_class']) || !is_numeric($body['hit_points'])) {
        bad_request();
    }
    $tags = [];
    if (isset($body['tags'])) {
        if (!is_array($body['tags'])) {
            bad_request('invalid tags');
        }
        foreach ($body['tags'] as $tag) {
            if (!is_string($tag)) {
                bad_request('invalid tags');
            }
        }
        $tags = array_values($body['tags']);
    }

    $slug = $body['slug'];
    $stmt = $db->prepare('SELECT slug FROM monsters WHERE slug = ?');
    $stmt->execute([$slug]);
    if ($stmt->fetch(PDO::FETCH_ASSOC) !== false) {
        conflict('monster already exists');
    }

    $monster = [
        'slug' => $slug,
        'name' => $body['name'],
        'cr' => $body['cr'],
        'armor_class' => (int)$body['armor_class'],
        'hit_points' => (int)$body['hit_points'],
        'tags' => $tags,
    ];

    $stmt = $db->prepare('INSERT INTO monsters (slug, data) VALUES (?, ?)');
    $stmt->execute([$slug, json_encode($monster)]);

    send_json([
        'slug' => $monster['slug'],
        'name' => $monster['name'],
        'cr' => $monster['cr'],
        'armor_class' => $monster['armor_class'],
        'hit_points' => $monster['hit_points'],
    ], 201);
}

if ($method === 'GET' && preg_match('#^/v1/compendium/monsters/([^/]+)$#', $path, $pm)) {
    $slug = $pm[1];
    $stmt = $db->prepare('SELECT data FROM monsters WHERE slug = ?');
    $stmt->execute([$slug]);
    $row = $stmt->fetch(PDO::FETCH_ASSOC);
    if ($row === false) {
        not_found('monster not found');
    }
    send_json(json_decode($row['data'], true));
}

if ($method === 'POST' && $path === '/v1/compendium/items') {
    $body = read_json_body();
    if ($body === null || !isset($body['slug'], $body['name'], $body['type'], $body['rarity'], $body['cost_gp'])
        || !is_valid_slug($body['slug']) || !is_string($body['name']) || !is_string($body['type'])
        || !is_string($body['rarity']) || !is_numeric($body['cost_gp'])) {
        bad_request();
    }

    $slug = $body['slug'];
    $stmt = $db->prepare('SELECT slug FROM items WHERE slug = ?');
    $stmt->execute([$slug]);
    if ($stmt->fetch(PDO::FETCH_ASSOC) !== false) {
        conflict('item already exists');
    }

    $item = [
        'slug' => $slug,
        'name' => $body['name'],
        'type' => $body['type'],
        'rarity' => $body['rarity'],
        'cost_gp' => (int)$body['cost_gp'],
    ];

    $stmt = $db->prepare('INSERT INTO items (slug, data) VALUES (?, ?)');
    $stmt->execute([$slug, json_encode($item)]);

    send_json($item, 201);
}

if ($method === 'GET' && preg_match('#^/v1/compendium/items/([^/]+)$#', $path, $pm)) {
    $slug = $pm[1];
    $stmt = $db->prepare('SELECT data FROM items WHERE slug = ?');
    $stmt->execute([$slug]);
    $row = $stmt->fetch(PDO::FETCH_ASSOC);
    if ($row === false) {
        not_found('item not found');
    }
    send_json(json_decode($row['data'], true));
}

// ---------------------------------------------------------------------------
