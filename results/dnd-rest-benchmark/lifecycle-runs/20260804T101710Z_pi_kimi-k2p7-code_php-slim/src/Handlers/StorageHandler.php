<?php

declare(strict_types=1);

use Psr\Http\Message\ResponseInterface as Response;
use Psr\Http\Message\ServerRequestInterface as Request;
use Slim\App;

/**
 * Storage introspection and reset endpoints.
 */
final class StorageHandler
{
    public function __construct(
        private GameDatabase $db,
    ) {}

    public function register(App $app): void
    {
        $app->get('/v1/storage/status', $this->status(...));
        $app->post('/v1/storage/reset', $this->reset(...));
    }

    private function status(Request $request, Response $response): Response
    {
        return respondJson($response, 200, [
            'driver' => 'sqlite',
            'schema_version' => GameDatabase::SCHEMA_VERSION,
            'initialized' => $this->db->isInitialized(),
        ]);
    }

    private function reset(Request $request, Response $response): Response
    {
        try {
            $this->db->reset();
            return respondJson($response, 200, ['ok' => true, 'schema_version' => GameDatabase::SCHEMA_VERSION]);
        } catch (Throwable $e) {
            return respondJson($response, 500, ['error' => 'reset failed']);
        }
    }
}
