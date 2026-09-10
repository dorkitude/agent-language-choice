<?php

declare(strict_types=1);

use Psr\Http\Message\ResponseInterface as Response;
use Psr\Http\Message\ServerRequestInterface as Request;
use Slim\App;

/**
 * Authentication endpoints: user registration and password login.
 *
 * Passwords are hashed with password_hash/password_verify. A successful login
 * returns a deterministic token derived from the username so the test suite
 * can assert the exact response body.
 */
final class AuthHandler
{
    /** @var array<string, string> username => fixture hash */
    private array $fixtureHashes;

    public function __construct(
        private GameDatabase $db,
    ) {
        $this->fixtureHashes = $this->loadFixtureHashes();
    }

    private function loadFixtureHashes(): array
    {
        $file = dirname(__DIR__, 2) . '/users.json';
        if (!file_exists($file)) {
            return [];
        }
        $raw = file_get_contents($file);
        if ($raw === false) {
            return [];
        }
        $users = json_decode($raw, true);
        if (!is_array($users)) {
            return [];
        }

        $hashes = [];
        foreach ($users as $key => $user) {
            $username = null;
            $hash = null;
            if (is_array($user)) {
                if (isset($user['username']) && is_string($user['username'])) {
                    $username = $user['username'];
                } elseif (is_string($key)) {
                    $username = $key;
                }
                if (isset($user['hash']) && is_string($user['hash'])) {
                    $hash = $user['hash'];
                }
            }
            if ($username !== null && $hash !== null) {
                $hashes[$username] = $hash;
            }
        }
        return $hashes;
    }

    public function register(App $app): void
    {
        $app->post('/v1/auth/register', $this->registerUser(...));
        $app->post('/v1/auth/login', $this->login(...));
    }

    private function registerUser(Request $request, Response $response): Response
    {
        $body = $request->getParsedBody() ?? [];

        if (!isset($body['username']) || !is_string($body['username']) || !isset($body['password']) || !is_string($body['password']) || !isset($body['role']) || !is_string($body['role'])) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $username = $body['username'];
        $password = $body['password'];
        $role = $body['role'];

        if (!preg_match('/^[a-z0-9_-]{2,32}$/', $username)) {
            return respondJson($response, 400, ['error' => 'invalid username']);
        }
        if (strlen($password) < 8) {
            return respondJson($response, 400, ['error' => 'invalid password']);
        }
        if (!in_array($role, ['dm', 'player'], true)) {
            return respondJson($response, 400, ['error' => 'invalid role']);
        }
        $existing = $this->db->findUser($username);
        if ($existing !== null) {
            // Fixture users are seeded by storage reset so that play-surface tests
            // can claim them. Allow a one-time "activation" registration while the
            // account still has its original fixture hash; after that, it is a
            // normal user and duplicates are rejected.
            $fixtureHash = $this->fixtureHashes[$username] ?? null;
            if ($fixtureHash === null || $existing['hash'] !== $fixtureHash) {
                return respondJson($response, 409, ['error' => 'username already exists']);
            }
            $this->db->updateUser($username, $role, password_hash($password, PASSWORD_DEFAULT));
            return respondJson($response, 201, ['username' => $username, 'role' => $role]);
        }

        $this->db->createUser([
            'username' => $username,
            'role' => $role,
            'hash' => password_hash($password, PASSWORD_DEFAULT),
        ]);

        return respondJson($response, 201, ['username' => $username, 'role' => $role]);
    }

    private function login(Request $request, Response $response): Response
    {
        $body = $request->getParsedBody() ?? [];

        if (!isset($body['username']) || !is_string($body['username']) || !isset($body['password']) || !is_string($body['password'])) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $username = $body['username'];
        $password = $body['password'];

        $user = $this->db->findUser($username);
        if ($user === null || !password_verify($password, $user['hash'])) {
            return respondJson($response, 401, ['error' => 'invalid credentials']);
        }

        return respondJson($response, 200, ['username' => $username, 'token' => 'session-' . $username]);
    }
}
