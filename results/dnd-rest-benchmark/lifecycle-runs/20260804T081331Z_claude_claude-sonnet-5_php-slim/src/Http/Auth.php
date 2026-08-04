<?php

declare(strict_types=1);

namespace App\Http;

use Psr\Http\Message\ServerRequestInterface as Request;

/** Resolves the `Authorization: Bearer session-<username>` header into an actor identity. */
final class Auth
{
    /**
     * Returns the authenticated actor (with 'username' and 'role'), or null if missing/invalid.
     * The play surface derives identity directly from the session token: the `dm` username is
     * the campaign DM, every other username is a player. No prior registration is required.
     */
    public static function actor(Request $request): ?array
    {
        $header = $request->getHeaderLine('Authorization');
        if (!preg_match('/^Bearer\s+session-(.+)$/', $header, $matches)) {
            return null;
        }

        $username = $matches[1];

        return [
            'username' => $username,
            'role' => $username === 'dm' ? 'dm' : 'player',
        ];
    }
}
