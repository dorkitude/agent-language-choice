<?php

namespace App\Auth;

use App\Storage\KvStore;
use App\Support\Json;
use Symfony\Component\HttpFoundation\JsonResponse;

/**
 * Handlers for account endpoints (/v1/auth/*). Users are stored as a JSON
 * document under the "users" kv_store key (see App\Storage\KvStore),
 * keyed by username.
 */
final class AuthController
{
    private function withUsersState(callable $fn): mixed
    {
        return KvStore::withState('users', ['users' => []], $fn);
    }

    public function register(array $body): JsonResponse
    {
        $username = $body['username'] ?? null;
        $password = $body['password'] ?? null;
        $role = $body['role'] ?? null;

        if (!is_string($username) || !preg_match('/^[a-z0-9_-]{2,32}$/', $username)) {
            return Json::error('invalid username');
        }
        if (!is_string($password) || strlen($password) < 8) {
            return Json::error('invalid password');
        }
        if (!is_string($role) || !in_array($role, ['dm', 'player'], true)) {
            return Json::error('invalid role');
        }

        return $this->withUsersState(function (array &$state) use ($username, $password, $role) {
            if (isset($state['users'][$username])) {
                return Json::error('username already exists', 409);
            }

            $state['users'][$username] = [
                'username' => $username,
                'password_hash' => password_hash($password, PASSWORD_DEFAULT),
                'role' => $role,
            ];

            return new JsonResponse(['username' => $username, 'role' => $role], 201);
        });
    }

    public function login(array $body): JsonResponse
    {
        $username = $body['username'] ?? null;
        $password = $body['password'] ?? null;

        if (!is_string($username) || $username === '' || !is_string($password) || $password === '') {
            return Json::error('invalid request');
        }

        return $this->withUsersState(function (array &$state) use ($username, $password) {
            $user = $state['users'][$username] ?? null;
            if ($user === null || !password_verify($password, $user['password_hash'])) {
                return Json::error('invalid credentials', 401);
            }

            return new JsonResponse(['username' => $username, 'token' => 'session-' . $username]);
        });
    }
}
