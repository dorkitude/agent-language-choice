<?php

declare(strict_types=1);

namespace App\Routes;

use App\Http\Json;
use App\Storage\Database;
use Psr\Http\Message\ResponseInterface as Response;
use Psr\Http\Message\ServerRequestInterface as Request;
use Slim\App;

final class StorageRoutes
{
    public static function register(App $app, string $dbFile): void
    {
        $app->get('/v1/storage/status', function (Request $request, Response $response) use ($dbFile) {
            Database::connect($dbFile);

            return Json::response($response, [
                'driver' => 'sqlite',
                'schema_version' => Database::SCHEMA_VERSION,
                'initialized' => true,
            ]);
        });

        $app->post('/v1/storage/reset', function (Request $request, Response $response) use ($dbFile) {
            $pdo = Database::connect($dbFile);
            Database::resetSchema($pdo);

            return Json::response($response, [
                'ok' => true,
                'schema_version' => Database::SCHEMA_VERSION,
            ]);
        });
    }
}
