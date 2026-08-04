<?php

declare(strict_types=1);

/**
 * HTTP helpers for the built-in PHP server.
 */

function getMethod(): string
{
    return $_SERVER['REQUEST_METHOD'] ?? 'GET';
}

function getPath(): string
{
    return parse_url($_SERVER['REQUEST_URI'] ?? '/', PHP_URL_PATH) ?: '/';
}

/**
 * Read the JSON request body. Returns an empty array for an empty body,
 * otherwise returns whatever json_decode produces (array, string, null, etc.).
 */
function parseInput(): mixed
{
    $raw = file_get_contents('php://input');
    return $raw !== '' ? json_decode($raw, true) : [];
}

function sendJson(int $code, array $body): void
{
    http_response_code($code);
    echo json_encode($body, JSON_UNESCAPED_SLASHES) . "\n";
    exit;
}

function sendError(int $code, string $message): void
{
    sendJson($code, ['error' => $message]);
}
