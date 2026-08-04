<?php

namespace App\Health;

use Symfony\Component\HttpFoundation\JsonResponse;

/** Handler for the liveness probe (GET /health). */
final class HealthController
{
    public function check(): JsonResponse
    {
        return new JsonResponse(['ok' => true]);
    }
}
