<?php

declare(strict_types=1);

namespace App\Http;

use Symfony\Component\HttpFoundation\JsonResponse;
use Symfony\Component\HttpFoundation\Request;

/**
 * Shared HTTP utilities for the DM tools API.
 */
final class HttpHelper
{
    /**
     * Decode the JSON request body into an associative array.
     *
     * An empty body is treated as an empty array to keep POST endpoints without
     * bodies (e.g. reset) convenient. Invalid JSON returns null so callers can
     * emit a 400 response.
     */
    public static function parseJsonBody(Request $request): ?array
    {
        $content = $request->getContent();
        if ($content === '') {
            return [];
        }

        try {
            return json_decode($content, true, 512, JSON_THROW_ON_ERROR);
        } catch (\Throwable) {
            return null;
        }
    }

    public static function error(string $message, int $status = 400): JsonResponse
    {
        return new JsonResponse(['error' => $message], $status);
    }
}
