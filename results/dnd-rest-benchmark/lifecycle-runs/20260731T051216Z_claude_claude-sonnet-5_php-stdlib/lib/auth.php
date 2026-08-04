<?php
declare(strict_types=1);

// Auth helpers.
// ---------------------------------------------------------------------------

function load_user(PDO $db, string $username): ?array {
    $stmt = $db->prepare('SELECT data FROM users WHERE username = ?');
    $stmt->execute([$username]);
    $row = $stmt->fetch(PDO::FETCH_ASSOC);
    return $row ? json_decode($row['data'], true) : null;
}

function save_user(PDO $db, string $username, array $user): void {
    $stmt = $db->prepare('INSERT OR REPLACE INTO users (username, data) VALUES (?, ?)');
    $stmt->execute([$username, json_encode($user)]);
}

function hash_password(string $password): string {
    return password_hash($password, PASSWORD_BCRYPT);
}

function verify_password(string $password, string $hash): bool {
    return password_verify($password, $hash);
}

// Resolves the caller's session token (`Authorization: Bearer session-<username>`)
// to an actor identity, or sends 401 if the header is missing/malformed.
// The play surface treats any well-formed session token as a valid actor;
// the "dm" username is the sole DM, everyone else is a player. A registered
// user record (if present) supplies the role instead, so real /v1/auth
// accounts keep working.
function require_actor(PDO $db): array {
    $header = $_SERVER['HTTP_AUTHORIZATION'] ?? '';
    if (!preg_match('/^Bearer\s+session-(.+)$/', $header, $m)) {
        unauthorized('missing or invalid authorization header');
    }
    $username = $m[1];
    $user = load_user($db, $username);
    if ($user !== null) {
        return $user;
    }
    return [
        'username' => $username,
        'role' => $username === 'dm' ? 'dm' : 'player',
    ];
}

function forbidden(string $message = 'forbidden'): void {
    send_json(['error' => $message], 403);
}

// ---------------------------------------------------------------------------
