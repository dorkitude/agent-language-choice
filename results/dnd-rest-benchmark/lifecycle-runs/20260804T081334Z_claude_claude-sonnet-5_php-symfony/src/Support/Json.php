<?php

namespace App\Support;

use Symfony\Component\HttpFoundation\JsonResponse;
use Symfony\Component\HttpFoundation\Request;

/**
 * Small helpers shared by every controller: building error responses and
 * decoding the JSON request body into an associative array.
 */
final class Json
{
    private function __construct()
    {
    }

    public static function error(string $message, int $status = 400): JsonResponse
    {
        return new JsonResponse(['error' => $message], $status);
    }

    /**
     * Returns [] for an empty body, the decoded associative array for valid
     * JSON objects/arrays, or null when the body is present but not valid
     * JSON (callers should turn null into a 400 "invalid json" response).
     */
    public static function parseBody(Request $request): ?array
    {
        $content = $request->getContent();
        if ($content === '' || $content === null) {
            return [];
        }
        $data = json_decode($content, true);
        if (!is_array($data)) {
            return null;
        }
        return $data;
    }
}
