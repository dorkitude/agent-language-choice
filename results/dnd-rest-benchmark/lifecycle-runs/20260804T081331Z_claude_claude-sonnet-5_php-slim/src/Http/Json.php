<?php

declare(strict_types=1);

namespace App\Http;

use Psr\Http\Message\ResponseInterface as Response;
use Psr\Http\Message\ServerRequestInterface as Request;

/**
 * Shared helpers for reading JSON request bodies and writing JSON responses.
 * Every route handler in this app goes through these two methods so the
 * response envelope (Content-Type, encoding) stays consistent.
 */
final class Json
{
    public static function response(Response $response, mixed $data, int $status = 200): Response
    {
        $response->getBody()->write(json_encode($data));

        return $response->withHeader('Content-Type', 'application/json')->withStatus($status);
    }

    /**
     * Decodes the request body as JSON. Non-object/array payloads (or
     * invalid JSON) intentionally collapse to an empty array so route
     * handlers can treat every field access as "missing" rather than
     * needing a separate malformed-JSON branch.
     */
    public static function parseBody(Request $request): array
    {
        $raw = (string) $request->getBody();
        $data = json_decode($raw, true);

        return is_array($data) ? $data : [];
    }
}
