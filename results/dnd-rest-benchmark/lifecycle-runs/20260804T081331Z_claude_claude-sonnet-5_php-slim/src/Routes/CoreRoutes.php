<?php

declare(strict_types=1);

namespace App\Routes;

use App\Http\Json;
use Psr\Http\Message\ResponseInterface as Response;
use Psr\Http\Message\ServerRequestInterface as Request;
use Slim\App;

/** Health check plus stateless dice/ability-check math (no persistence). */
final class CoreRoutes
{
    public static function register(App $app): void
    {
        $app->get('/health', function (Request $request, Response $response) {
            return Json::response($response, ['ok' => true]);
        });

        $app->post('/v1/dice/stats', function (Request $request, Response $response) {
            $body = Json::parseBody($request);
            $expression = $body['expression'] ?? null;

            if (!is_string($expression) || !preg_match('/^(\d+)d(\d+)(?:([+-])(\d+))?$/', $expression, $m)) {
                return Json::response($response, ['error' => 'invalid expression'], 400);
            }

            $count = (int) $m[1];
            $sides = (int) $m[2];
            $modifier = 0;
            if (isset($m[3])) {
                $modifier = (int) $m[4];
                if ($m[3] === '-') {
                    $modifier = -$modifier;
                }
            }

            if ($count <= 0 || $sides <= 0) {
                return Json::response($response, ['error' => 'invalid expression'], 400);
            }

            $min = $count * 1 + $modifier;
            $max = $count * $sides + $modifier;
            $average = ($count * ($sides + 1) / 2) + $modifier;

            return Json::response($response, [
                'dice_count' => $count,
                'sides' => $sides,
                'modifier' => $modifier,
                'min' => $min,
                'max' => $max,
                'average' => $average,
            ]);
        });

        $app->post('/v1/checks/ability', function (Request $request, Response $response) {
            $body = Json::parseBody($request);
            $roll = $body['roll'] ?? null;
            $modifier = $body['modifier'] ?? null;
            $dc = $body['dc'] ?? null;

            if (!is_numeric($roll) || !is_numeric($modifier) || !is_numeric($dc)) {
                return Json::response($response, ['error' => 'invalid request'], 400);
            }

            $total = $roll + $modifier;
            $success = $total >= $dc;
            $margin = $total - $dc;

            return Json::response($response, [
                'total' => $total,
                'success' => $success,
                'margin' => $margin,
            ]);
        });
    }
}
