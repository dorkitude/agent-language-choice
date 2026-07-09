<?php

declare(strict_types=1);

require __DIR__ . '/vendor/autoload.php';

use Symfony\Component\HttpFoundation\JsonResponse;
use Symfony\Component\HttpFoundation\Request;
use Symfony\Component\Routing\Exception\MethodNotAllowedException;
use Symfony\Component\Routing\Exception\ResourceNotFoundException;
use Symfony\Component\Routing\Matcher\UrlMatcher;
use Symfony\Component\Routing\RequestContext;
use Symfony\Component\Routing\Route;
use Symfony\Component\Routing\RouteCollection;

function jsonBody(Request $request): ?array
{
    $content = $request->getContent();
    if ($content === '') {
        return [];
    }

    $data = json_decode($content, true);
    return is_array($data) ? $data : null;
}

function badRequest(string $message = 'bad request'): JsonResponse
{
    return new JsonResponse(['error' => $message], 400);
}

function isIntegerValue(mixed $value): bool
{
    return is_int($value);
}

function health(Request $request): JsonResponse
{
    return new JsonResponse(['ok' => true]);
}

function diceStats(Request $request): JsonResponse
{
    $body = jsonBody($request);
    if ($body === null || !isset($body['expression']) || !is_string($body['expression'])) {
        return badRequest('invalid expression');
    }

    if (!preg_match('/^([0-9]+)d([0-9]+)(?:([+-])([0-9]+))?$/', $body['expression'], $matches)) {
        return badRequest('invalid expression');
    }

    $count = (int) $matches[1];
    $sides = (int) $matches[2];
    if ($count <= 0 || $sides <= 0) {
        return badRequest('invalid expression');
    }

    $modifier = 0;
    if (isset($matches[3], $matches[4]) && $matches[3] !== '') {
        $modifier = (int) $matches[4];
        if ($matches[3] === '-') {
            $modifier = -$modifier;
        }
    }

    $min = $count + $modifier;
    $max = ($count * $sides) + $modifier;
    $average = ($min + $max) / 2;

    return new JsonResponse([
        'dice_count' => $count,
        'sides' => $sides,
        'modifier' => $modifier,
        'min' => $min,
        'max' => $max,
        'average' => fmod($average, 1.0) === 0.0 ? (int) $average : $average,
    ]);
}

function abilityCheck(Request $request): JsonResponse
{
    $body = jsonBody($request);
    if (
        $body === null
        || !array_key_exists('roll', $body)
        || !array_key_exists('modifier', $body)
        || !array_key_exists('dc', $body)
        || !isIntegerValue($body['roll'])
        || !isIntegerValue($body['modifier'])
        || !isIntegerValue($body['dc'])
    ) {
        return badRequest();
    }

    $total = $body['roll'] + $body['modifier'];
    $margin = $total - $body['dc'];

    return new JsonResponse([
        'total' => $total,
        'success' => $total >= $body['dc'],
        'margin' => $margin,
    ]);
}

function encounterMultiplier(int $monsterCount): float
{
    if ($monsterCount <= 1) {
        return 1.0;
    }
    if ($monsterCount === 2) {
        return 1.5;
    }
    if ($monsterCount <= 6) {
        return 2.0;
    }
    if ($monsterCount <= 10) {
        return 2.5;
    }
    if ($monsterCount <= 14) {
        return 3.0;
    }

    return 4.0;
}

function adjustedXp(Request $request): JsonResponse
{
    $body = jsonBody($request);
    if ($body === null || !isset($body['party'], $body['monsters']) || !is_array($body['party']) || !is_array($body['monsters'])) {
        return badRequest();
    }

    $xpByCr = [
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

    $thresholds = ['easy' => 0, 'medium' => 0, 'hard' => 0, 'deadly' => 0];
    foreach ($body['party'] as $member) {
        if (!is_array($member) || !isset($member['level']) || !isIntegerValue($member['level']) || !isset($levelThresholds[$member['level']])) {
            return badRequest();
        }

        foreach ($thresholds as $name => $value) {
            $thresholds[$name] = $value + $levelThresholds[$member['level']][$name];
        }
    }

    $baseXp = 0;
    $monsterCount = 0;
    foreach ($body['monsters'] as $monster) {
        if (
            !is_array($monster)
            || !isset($monster['cr'], $monster['count'])
            || !is_string($monster['cr'])
            || !isIntegerValue($monster['count'])
            || $monster['count'] <= 0
            || !array_key_exists($monster['cr'], $xpByCr)
        ) {
            return badRequest();
        }

        $baseXp += $xpByCr[$monster['cr']] * $monster['count'];
        $monsterCount += $monster['count'];
    }

    $multiplier = encounterMultiplier($monsterCount);
    $adjustedXp = $baseXp * $multiplier;
    $difficulty = 'trivial';
    foreach (['easy', 'medium', 'hard', 'deadly'] as $name) {
        if ($adjustedXp >= $thresholds[$name]) {
            $difficulty = $name;
        }
    }

    return new JsonResponse([
        'base_xp' => $baseXp,
        'monster_count' => $monsterCount,
        'multiplier' => fmod($multiplier, 1.0) === 0.0 ? (int) $multiplier : $multiplier,
        'adjusted_xp' => fmod($adjustedXp, 1.0) === 0.0 ? (int) $adjustedXp : $adjustedXp,
        'difficulty' => $difficulty,
        'thresholds' => $thresholds,
    ]);
}

function initiativeOrder(Request $request): JsonResponse
{
    $body = jsonBody($request);
    if ($body === null || !isset($body['combatants']) || !is_array($body['combatants'])) {
        return badRequest();
    }

    $combatants = [];
    foreach ($body['combatants'] as $combatant) {
        if (
            !is_array($combatant)
            || !isset($combatant['name'], $combatant['dex'], $combatant['roll'])
            || !is_string($combatant['name'])
            || !isIntegerValue($combatant['dex'])
            || !isIntegerValue($combatant['roll'])
        ) {
            return badRequest();
        }

        $combatants[] = [
            'name' => $combatant['name'],
            'dex' => $combatant['dex'],
            'score' => $combatant['roll'] + $combatant['dex'],
        ];
    }

    usort($combatants, static function (array $left, array $right): int {
        return ($right['score'] <=> $left['score'])
            ?: ($right['dex'] <=> $left['dex'])
            ?: ($left['name'] <=> $right['name']);
    });

    return new JsonResponse([
        'order' => array_map(
            static fn (array $combatant): array => ['name' => $combatant['name'], 'score' => $combatant['score']],
            $combatants
        ),
    ]);
}

function appRoutes(): RouteCollection
{
    $routes = new RouteCollection();
    $routes->add('health', new Route('/health', ['_controller' => 'health'], [], [], '', [], ['GET']));
    $routes->add('dice_stats', new Route('/v1/dice/stats', ['_controller' => 'diceStats'], [], [], '', [], ['POST']));
    $routes->add('ability_check', new Route('/v1/checks/ability', ['_controller' => 'abilityCheck'], [], [], '', [], ['POST']));
    $routes->add('adjusted_xp', new Route('/v1/encounters/adjusted-xp', ['_controller' => 'adjustedXp'], [], [], '', [], ['POST']));
    $routes->add('initiative_order', new Route('/v1/initiative/order', ['_controller' => 'initiativeOrder'], [], [], '', [], ['POST']));

    return $routes;
}

function appHandle(Request $request): JsonResponse
{
    $context = new RequestContext();
    $context->fromRequest($request);
    $matcher = new UrlMatcher(appRoutes(), $context);

    try {
        $parameters = $matcher->matchRequest($request);
        $controller = $parameters['_controller'];
        return $controller($request);
    } catch (ResourceNotFoundException) {
        return new JsonResponse(['error' => 'not found'], 404);
    } catch (MethodNotAllowedException) {
        return new JsonResponse(['error' => 'method not allowed'], 405);
    }
}

if (realpath($_SERVER['SCRIPT_FILENAME'] ?? '') === __FILE__) {
    appHandle(Request::createFromGlobals())->send();
}
