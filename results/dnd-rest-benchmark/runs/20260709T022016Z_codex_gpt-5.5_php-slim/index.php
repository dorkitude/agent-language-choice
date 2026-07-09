<?php
require __DIR__ . '/vendor/autoload.php';

use Psr\Http\Message\ResponseInterface as Response;
use Psr\Http\Message\ServerRequestInterface as Request;
use Slim\Factory\AppFactory;

$app = AppFactory::create();

function jsonResponse(Response $response, array $payload, int $status = 200): Response
{
    $response->getBody()->write(json_encode($payload));
    return $response
        ->withStatus($status)
        ->withHeader('Content-Type', 'application/json');
}

function jsonBody(Request $request): array
{
    $data = json_decode((string) $request->getBody(), true);
    return is_array($data) ? $data : [];
}

function badRequest(Response $response): Response
{
    return jsonResponse($response, ['error' => 'bad_request'], 400);
}

$app->get('/health', function (Request $request, Response $response) {
    return jsonResponse($response, ['ok' => true]);
});

$app->post('/v1/dice/stats', function (Request $request, Response $response) {
    $body = jsonBody($request);
    $expression = $body['expression'] ?? null;

    if (!is_string($expression) || !preg_match('/^([0-9]+)d([0-9]+)(?:([+-])([0-9]+))?$/', $expression, $matches)) {
        return badRequest($response);
    }

    $count = (int) $matches[1];
    $sides = (int) $matches[2];
    if ($count <= 0 || $sides <= 0) {
        return badRequest($response);
    }

    $modifier = 0;
    if (isset($matches[3], $matches[4]) && $matches[3] !== '') {
        $modifier = (int) $matches[4];
        if ($matches[3] === '-') {
            $modifier *= -1;
        }
    }

    return jsonResponse($response, [
        'dice_count' => $count,
        'sides' => $sides,
        'modifier' => $modifier,
        'min' => $count + $modifier,
        'max' => ($count * $sides) + $modifier,
        'average' => ($count * ($sides + 1) / 2) + $modifier,
    ]);
});

$app->post('/v1/checks/ability', function (Request $request, Response $response) {
    $body = jsonBody($request);
    $total = (int) ($body['roll'] ?? 0) + (int) ($body['modifier'] ?? 0);
    $dc = (int) ($body['dc'] ?? 0);

    return jsonResponse($response, [
        'total' => $total,
        'success' => $total >= $dc,
        'margin' => $total - $dc,
    ]);
});

$app->post('/v1/encounters/adjusted-xp', function (Request $request, Response $response) {
    $monsterXp = [
        '0' => 10,
        '1/8' => 25,
        '1/4' => 50,
        '1/2' => 100,
        '1' => 200,
        '2' => 450,
        '3' => 700,
        '4' => 1100,
        '5' => 1800,
    ];
    $levelThresholds = [
        3 => ['easy' => 75, 'medium' => 150, 'hard' => 225, 'deadly' => 400],
    ];

    $body = jsonBody($request);
    $baseXp = 0;
    $monsterCount = 0;

    foreach (($body['monsters'] ?? []) as $monster) {
        $cr = (string) ($monster['cr'] ?? '');
        if (!array_key_exists($cr, $monsterXp)) {
            return badRequest($response);
        }
        $count = (int) ($monster['count'] ?? 0);
        if ($count < 0) {
            return badRequest($response);
        }
        $baseXp += $monsterXp[$cr] * $count;
        $monsterCount += $count;
    }

    $multiplier = 4;
    if ($monsterCount <= 1) {
        $multiplier = 1;
    } elseif ($monsterCount === 2) {
        $multiplier = 1.5;
    } elseif ($monsterCount <= 6) {
        $multiplier = 2;
    } elseif ($monsterCount <= 10) {
        $multiplier = 2.5;
    } elseif ($monsterCount <= 14) {
        $multiplier = 3;
    }

    $thresholds = ['easy' => 0, 'medium' => 0, 'hard' => 0, 'deadly' => 0];
    foreach (($body['party'] ?? []) as $member) {
        $level = (int) ($member['level'] ?? 0);
        if (!array_key_exists($level, $levelThresholds)) {
            return badRequest($response);
        }
        foreach ($levelThresholds[$level] as $name => $threshold) {
            $thresholds[$name] += $threshold;
        }
    }

    $adjustedXp = $baseXp * $multiplier;
    $difficulty = 'trivial';
    foreach (['easy', 'medium', 'hard', 'deadly'] as $name) {
        if ($adjustedXp >= $thresholds[$name]) {
            $difficulty = $name;
        }
    }

    return jsonResponse($response, [
        'base_xp' => $baseXp,
        'monster_count' => $monsterCount,
        'multiplier' => $multiplier,
        'adjusted_xp' => $adjustedXp,
        'difficulty' => $difficulty,
        'thresholds' => $thresholds,
    ]);
});

$app->post('/v1/initiative/order', function (Request $request, Response $response) {
    $body = jsonBody($request);
    $combatants = $body['combatants'] ?? [];

    usort($combatants, function (array $a, array $b): int {
        $aScore = (int) ($a['roll'] ?? 0) + (int) ($a['dex'] ?? 0);
        $bScore = (int) ($b['roll'] ?? 0) + (int) ($b['dex'] ?? 0);

        if ($aScore !== $bScore) {
            return $bScore <=> $aScore;
        }

        $aDex = (int) ($a['dex'] ?? 0);
        $bDex = (int) ($b['dex'] ?? 0);
        if ($aDex !== $bDex) {
            return $bDex <=> $aDex;
        }

        return strcmp((string) ($a['name'] ?? ''), (string) ($b['name'] ?? ''));
    });

    $order = array_map(function (array $combatant): array {
        return [
            'name' => (string) ($combatant['name'] ?? ''),
            'score' => (int) ($combatant['roll'] ?? 0) + (int) ($combatant['dex'] ?? 0),
        ];
    }, $combatants);

    return jsonResponse($response, ['order' => $order]);
});

$app->run();
