<?php

declare(strict_types=1);

use Psr\Http\Message\ResponseInterface as Response;

/**
 * Write a JSON payload to a PSR-7 response.
 *
 * Preserves zero fractions (e.g. 10.0) and leaves forward slashes unescaped
 * so that the wire format remains identical to the original implementation.
 */
function respondJson(Response $response, int $status, mixed $data): Response
{
    $response->getBody()->write(json_encode($data, JSON_PRESERVE_ZERO_FRACTION | JSON_UNESCAPED_SLASHES));
    return $response->withStatus($status)->withHeader('Content-Type', 'application/json');
}
