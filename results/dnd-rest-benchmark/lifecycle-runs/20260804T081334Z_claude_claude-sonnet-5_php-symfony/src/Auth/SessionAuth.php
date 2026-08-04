<?php

namespace App\Auth;

use App\Storage\KvStore;
use Symfony\Component\HttpFoundation\Request;

/**
 * Resolves the `Authorization: Bearer session-<username>` header used by
 * protected endpoints into the acting user's record, looking it up against
 * the same "users" kv_store document AuthController writes to. Returns null
 * only for a missing/malformed header - callers should turn that into a 401.
 * A well-formed header for a username with no registered account still
 * resolves to an actor (with a null role), since the token itself is valid
 * credentials; callers should turn a role mismatch (including a null role)
 * into a 403, matching "authenticated but not permitted".
 */
final class SessionAuth
{
    private function __construct()
    {
    }

    public static function authenticate(Request $request): ?array
    {
        $header = $request->headers->get('Authorization');
        if (!is_string($header) || !str_starts_with($header, 'Bearer session-')) {
            return null;
        }

        $username = substr($header, strlen('Bearer session-'));
        if ($username === '') {
            return null;
        }

        return KvStore::withState('users', ['users' => []], static function (array &$state) use ($username) {
            $user = $state['users'][$username] ?? null;
            return ['username' => $username, 'role' => $user['role'] ?? null];
        });
    }
}
