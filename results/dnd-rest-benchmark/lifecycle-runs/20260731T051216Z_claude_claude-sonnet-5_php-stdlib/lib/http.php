<?php
declare(strict_types=1);

// HTTP I/O helpers shared by every route below.
// ---------------------------------------------------------------------------

function read_json_body(): ?array {
    $raw = file_get_contents('php://input');
    if ($raw === false || $raw === '') {
        return null;
    }
    $data = json_decode($raw, true);
    if (!is_array($data)) {
        return null;
    }
    return $data;
}

// send_json() (and the error helpers built on it) always exit(); routes rely
// on this to short-circuit validation failures without explicit `return`.
function send_json($data, int $status = 200): void {
    http_response_code($status);
    echo json_encode($data);
    exit;
}

function bad_request(string $message = 'invalid request'): void {
    send_json(['error' => $message], 400);
}

function not_found(string $message = 'not found'): void {
    send_json(['error' => $message], 404);
}

function unauthorized(string $message = 'unauthorized'): void {
    send_json(['error' => $message], 401);
}

function conflict(string $message = 'conflict'): void {
    send_json(['error' => $message], 409);
}

// ---------------------------------------------------------------------------
// Field validation helpers.
// ---------------------------------------------------------------------------

function is_valid_int_range($value, int $min, int $max): bool {
    if (is_int($value)) {
        $intValue = $value;
    } elseif (is_float($value) && $value == (int)$value) {
        $intValue = (int)$value;
    } else {
        return false;
    }
    return $intValue >= $min && $intValue <= $max;
}

function is_valid_slug($value): bool {
    return is_string($value) && preg_match('/^[a-z0-9-]{1,64}$/', $value);
}

