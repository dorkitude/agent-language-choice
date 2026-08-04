<?php

declare(strict_types=1);

namespace App\Storage;

use PDO;

final class UserRepository
{
    public function __construct(private readonly PDO $pdo)
    {
    }

    public function all(): array
    {
        $users = [];
        foreach ($this->pdo->query('SELECT username, data FROM users') as $row) {
            $users[$row['username']] = json_decode($row['data'], true);
        }

        return $users;
    }

    public function save(string $username, array $user): void
    {
        $stmt = $this->pdo->prepare('INSERT OR REPLACE INTO users (username, data) VALUES (?, ?)');
        $stmt->execute([$username, json_encode($user)]);
    }

    public static function hashPassword(string $password): string
    {
        return password_hash($password, PASSWORD_DEFAULT);
    }

    public static function verifyPassword(string $password, string $hash): bool
    {
        return password_verify($password, $hash);
    }
}
