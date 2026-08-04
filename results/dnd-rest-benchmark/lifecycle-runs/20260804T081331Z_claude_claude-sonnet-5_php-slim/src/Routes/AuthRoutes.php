<?php

declare(strict_types=1);

namespace App\Routes;

use App\Http\Json;
use App\Storage\Database;
use App\Storage\UserRepository;
use Psr\Http\Message\ResponseInterface as Response;
use Psr\Http\Message\ServerRequestInterface as Request;
use Slim\App;

final class AuthRoutes
{
    public static function register(App $app, string $dbFile): void
    {
        $app->post('/v1/auth/register', function (Request $request, Response $response) use ($dbFile) {
            $repo = new UserRepository(Database::connect($dbFile));
            $body = Json::parseBody($request);
            $username = $body['username'] ?? null;
            $password = $body['password'] ?? null;
            $role = $body['role'] ?? null;

            if (!is_string($username) || !preg_match('/^[a-z0-9_-]{2,32}$/', $username)) {
                return Json::response($response, ['error' => 'invalid username'], 400);
            }
            if (!is_string($password) || strlen($password) < 8) {
                return Json::response($response, ['error' => 'invalid password'], 400);
            }
            if ($role !== 'dm' && $role !== 'player') {
                return Json::response($response, ['error' => 'invalid role'], 400);
            }

            $users = $repo->all();

            if (isset($users[$username])) {
                return Json::response($response, ['error' => 'username already exists'], 409);
            }

            $user = [
                'username' => $username,
                'password_hash' => UserRepository::hashPassword($password),
                'role' => $role,
            ];

            $repo->save($username, $user);

            return Json::response($response, [
                'username' => $username,
                'role' => $role,
            ], 201);
        });

        $app->post('/v1/auth/login', function (Request $request, Response $response) use ($dbFile) {
            $repo = new UserRepository(Database::connect($dbFile));
            $body = Json::parseBody($request);
            $username = $body['username'] ?? null;
            $password = $body['password'] ?? null;

            if (!is_string($username) || !is_string($password)) {
                return Json::response($response, ['error' => 'invalid request'], 400);
            }

            $users = $repo->all();
            $user = $users[$username] ?? null;

            if ($user === null || !UserRepository::verifyPassword($password, $user['password_hash'])) {
                return Json::response($response, ['error' => 'invalid credentials'], 401);
            }

            return Json::response($response, [
                'username' => $username,
                'token' => 'session-' . $username,
            ]);
        });
    }
}
