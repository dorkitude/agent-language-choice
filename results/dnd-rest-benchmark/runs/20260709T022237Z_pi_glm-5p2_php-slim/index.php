<?php
require __DIR__ . '/vendor/autoload.php';

use Psr\Http\Message\ResponseInterface as Response;
use Psr\Http\Message\ServerRequestInterface as Request;
use Psr\Log\LoggerInterface;
use Slim\Exception\HttpException;
use Slim\Factory\AppFactory;

$app = AppFactory::create();

// Slim 4 does NOT install routing/error middleware automatically. Without these,
// an HttpNotFoundException (unknown route) or any uncaught handler exception
// leaks as a PHP fatal error rendered as HTML with a 200 status. The stack is
// LIFO, so adding ErrorMiddleware LAST makes it the outermost handler and lets
// it render clean JSON error responses (404 / 500) instead.
$app->addRoutingMiddleware();
$errorMiddleware = $app->addErrorMiddleware(false, false, false);

// Force JSON for every error response (404 / 405 / 500 ...) so the API is
// consistently JSON per the contract, regardless of the client's Accept header.
$errorMiddleware->setDefaultErrorHandler(
    function (Request $request, Throwable $exception, bool $displayErrorDetails, bool $logErrors, bool $logErrorDetails, ?LoggerInterface $logger = null) use ($app): Response {
        $status = $exception instanceof HttpException ? (int)$exception->getCode() : 500;
        if ($status < 400 || $status > 599) {
            $status = 500;
        }
        // HttpException messages are user-facing and safe; hide internals otherwise.
        $message = $exception instanceof HttpException ? $exception->getMessage() : 'internal server error';
        $response = $app->getResponseFactory()->createResponse($status);
        $response->getBody()->write(json_encode(['error' => $message]));
        return $response->withHeader('Content-Type', 'application/json');
    }
);

/**
 * Encode a number as int when it is a whole value, otherwise keep it float.
 * Keeps JSON output matching examples like `"average": 10` and `"multiplier": 2`.
 */
function num($v)
{
    if (is_float($v) && floor($v) == $v) {
        return (int)$v;
    }
    return $v;
}

function jsonResp(Response $response, $data, int $status = 200): Response
{
    $response->getBody()->write(json_encode($data, JSON_THROW_ON_ERROR));
    return $response
        ->withHeader('Content-Type', 'application/json')
        ->withStatus($status);
}

function parseBody(Request $request): ?array
{
    $raw = (string)$request->getBody();
    $data = json_decode($raw, true);
    return is_array($data) ? $data : null;
}

// ---- GET /health ----------------------------------------------------------
$app->get('/health', function (Request $request, Response $response): Response {
    return jsonResp($response, ['ok' => true]);
});

// ---- POST /v1/dice/stats --------------------------------------------------
$app->post('/v1/dice/stats', function (Request $request, Response $response): Response {
    $data = parseBody($request);
    if ($data === null || !array_key_exists('expression', $data)) {
        return jsonResp($response, ['error' => 'invalid request'], 400);
    }
    $expr = (string)$data['expression'];
    if (!preg_match('/^(\d+)d(\d+)(?:([+-])(\d+))?$/', $expr, $m)) {
        return jsonResp($response, ['error' => 'invalid expression'], 400);
    }
    $count = (int)$m[1];
    $sides = (int)$m[2];
    if ($count <= 0 || $sides <= 0) {
        return jsonResp($response, ['error' => 'invalid expression'], 400);
    }
    $modifier = 0;
    if (isset($m[3])) {
        $modifier = ($m[3] === '-') ? -((int)$m[4]) : (int)$m[4];
    }
    $min = $count + $modifier;              // count * 1 + modifier
    $max = $count * $sides + $modifier;
    $average = ($min + $max) / 2;

    return jsonResp($response, [
        'dice_count' => $count,
        'sides'      => $sides,
        'modifier'   => $modifier,
        'min'        => $min,
        'max'        => $max,
        'average'    => num($average),
    ]);
});

// ---- POST /v1/checks/ability ---------------------------------------------
$app->post('/v1/checks/ability', function (Request $request, Response $response): Response {
    $data = parseBody($request);
    if ($data === null) {
        return jsonResp($response, ['error' => 'invalid request'], 400);
    }
    $roll = (int)($data['roll'] ?? 0);
    $modifier = (int)($data['modifier'] ?? 0);
    $dc = (int)($data['dc'] ?? 0);

    $total = $roll + $modifier;
    $success = $total >= $dc;
    $margin = $total - $dc;

    return jsonResp($response, [
        'total'   => $total,
        'success' => $success,
        'margin'  => $margin,
    ]);
});

// ---- POST /v1/encounters/adjusted-xp -------------------------------------
$app->post('/v1/encounters/adjusted-xp', function (Request $request, Response $response): Response {
    $data = parseBody($request);
    if ($data === null) {
        return jsonResp($response, ['error' => 'invalid request'], 400);
    }

    $xpTable = [
        '0'   => 10,
        '1/8' => 25,
        '1/4' => 50,
        '1/2' => 100,
        '1'   => 200,
        '2'   => 450,
        '3'   => 700,
        '4'   => 1100,
        '5'   => 1800,
    ];

    // Per-level encounter thresholds (first benchmark suite: level 3 only).
    $levelThresholds = [
        3 => ['easy' => 75, 'medium' => 150, 'hard' => 225, 'deadly' => 400],
    ];

    $monsters = $data['monsters'] ?? [];
    if (!is_array($monsters)) {
        return jsonResp($response, ['error' => 'invalid monsters'], 400);
    }

    $baseXp = 0;
    $monsterCount = 0;
    foreach ($monsters as $monster) {
        $cr = (string)($monster['cr'] ?? '');
        if (!array_key_exists($cr, $xpTable)) {
            return jsonResp($response, ['error' => 'unsupported cr'], 400);
        }
        $count = (int)($monster['count'] ?? 0);
        $baseXp += $xpTable[$cr] * $count;
        $monsterCount += $count;
    }

    $multiplier = 1.0;
    if ($monsterCount >= 15) {
        $multiplier = 4.0;
    } elseif ($monsterCount >= 11) {
        $multiplier = 3.0;
    } elseif ($monsterCount >= 7) {
        $multiplier = 2.5;
    } elseif ($monsterCount >= 3) {
        $multiplier = 2.0;
    } elseif ($monsterCount === 2) {
        $multiplier = 1.5;
    } else {
        $multiplier = 1.0; // 0 or 1
    }

    $adjustedXp = $baseXp * $multiplier;

    $party = $data['party'] ?? [];
    if (!is_array($party)) {
        return jsonResp($response, ['error' => 'invalid party'], 400);
    }

    $thr = ['easy' => 0, 'medium' => 0, 'hard' => 0, 'deadly' => 0];
    foreach ($party as $member) {
        $level = (int)($member['level'] ?? 0);
        if (!isset($levelThresholds[$level])) {
            return jsonResp($response, ['error' => 'unsupported level'], 400);
        }
        foreach (['easy', 'medium', 'hard', 'deadly'] as $k) {
            $thr[$k] += $levelThresholds[$level][$k];
        }
    }

    if ($adjustedXp >= $thr['deadly']) {
        $difficulty = 'deadly';
    } elseif ($adjustedXp >= $thr['hard']) {
        $difficulty = 'hard';
    } elseif ($adjustedXp >= $thr['medium']) {
        $difficulty = 'medium';
    } elseif ($adjustedXp >= $thr['easy']) {
        $difficulty = 'easy';
    } else {
        $difficulty = 'trivial';
    }

    return jsonResp($response, [
        'base_xp'      => $baseXp,
        'monster_count' => $monsterCount,
        'multiplier'   => num($multiplier),
        'adjusted_xp'  => num($adjustedXp),
        'difficulty'   => $difficulty,
        'thresholds'   => $thr,
    ]);
});

// ---- POST /v1/initiative/order -------------------------------------------
$app->post('/v1/initiative/order', function (Request $request, Response $response): Response {
    $data = parseBody($request);
    if ($data === null) {
        return jsonResp($response, ['error' => 'invalid request'], 400);
    }
    $combatants = $data['combatants'] ?? [];
    if (!is_array($combatants)) {
        return jsonResp($response, ['error' => 'invalid combatants'], 400);
    }

    $rows = [];
    foreach ($combatants as $c) {
        $name = (string)($c['name'] ?? '');
        $dex = (int)($c['dex'] ?? 0);
        $roll = (int)($c['roll'] ?? 0);
        $rows[] = [
            'name'  => $name,
            'dex'   => $dex,
            'score' => $roll + $dex,
        ];
    }

    usort($rows, function (array $a, array $b): int {
        if ($a['score'] !== $b['score']) {
            return $b['score'] <=> $a['score']; // score descending
        }
        if ($a['dex'] !== $b['dex']) {
            return $b['dex'] <=> $a['dex']; // dex descending
        }
        return $a['name'] <=> $b['name']; // name ascending
    });

    $order = array_map(function (array $r): array {
        return ['name' => $r['name'], 'score' => $r['score']];
    }, $rows);

    return jsonResp($response, ['order' => $order]);
});

$app->run();
