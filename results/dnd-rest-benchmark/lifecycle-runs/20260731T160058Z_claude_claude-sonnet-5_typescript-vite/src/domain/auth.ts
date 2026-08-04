/**
 * User registration and login.
 *
 * Users are cached in-memory (`users`) for lookups and mirrored to SQLite via
 * `persistUser`; `loadUsersFromDb` rehydrates the cache at startup. Passwords are
 * hashed with scrypt using a per-user random salt and compared with a
 * timing-safe equality check.
 */

import { randomBytes, scryptSync, timingSafeEqual } from 'node:crypto';
import { getDb } from '../db.ts';
import type { ApiResult, JsonValue } from '../types.ts';

interface UserRecord {
  username: string;
  role: 'dm' | 'player';
  passwordHash: string;
  salt: string;
}

const users = new Map<string, UserRecord>();

function persistUser(user: UserRecord): void {
  const db = getDb();
  db.prepare(
    'INSERT INTO users (username, role, password_hash, salt) VALUES (?, ?, ?, ?) ' +
      'ON CONFLICT(username) DO UPDATE SET role = excluded.role, password_hash = excluded.password_hash, salt = excluded.salt',
  ).run(user.username, user.role, user.passwordHash, user.salt);
}

export function loadUsersFromDb(): void {
  const db = getDb();
  const rows = db.prepare('SELECT username, role, password_hash, salt FROM users').all() as {
    username: string;
    role: 'dm' | 'player';
    password_hash: string;
    salt: string;
  }[];
  for (const row of rows) {
    users.set(row.username, { username: row.username, role: row.role, passwordHash: row.password_hash, salt: row.salt });
  }
}

export function clearUsers(): void {
  users.clear();
}

export function getUserRole(username: string): 'dm' | 'player' | undefined {
  return users.get(username)?.role;
}

function hashPassword(password: string, salt: string): string {
  return scryptSync(password, salt, 64).toString('hex');
}

function verifyPassword(password: string, salt: string, expectedHash: string): boolean {
  const actual = Buffer.from(hashPassword(password, salt), 'hex');
  const expected = Buffer.from(expectedHash, 'hex');
  if (actual.length !== expected.length) return false;
  return timingSafeEqual(actual, expected);
}

const USERNAME_RE = /^[a-z0-9_-]{2,32}$/;

export function registerUser(body: JsonValue): ApiResult {
  const username = body.username;
  if (typeof username !== 'string' || !USERNAME_RE.test(username)) {
    return {
      status: 400,
      body: { error: 'username must be 2-32 characters of lowercase letters, digits, _, or -' },
    };
  }

  const password = body.password;
  if (typeof password !== 'string' || password.length < 8) {
    return { status: 400, body: { error: 'password must be at least 8 characters' } };
  }

  const role = body.role;
  if (role !== 'dm' && role !== 'player') {
    return { status: 400, body: { error: 'role must be either dm or player' } };
  }

  if (users.has(username)) {
    return { status: 409, body: { error: 'username already exists' } };
  }

  const salt = randomBytes(16).toString('hex');
  const passwordHash = hashPassword(password, salt);
  const user: UserRecord = { username, role, passwordHash, salt };
  users.set(username, user);
  persistUser(user);

  return { status: 201, body: { username, role } };
}

export function loginUser(body: JsonValue): ApiResult {
  const username = body.username;
  const password = body.password;
  if (typeof username !== 'string' || typeof password !== 'string') {
    return { status: 400, body: { error: 'username and password must be strings' } };
  }

  const user = users.get(username);
  if (!user || !verifyPassword(password, user.salt, user.passwordHash)) {
    return { status: 401, body: { error: 'invalid credentials' } };
  }

  return { status: 200, body: { username: user.username, token: `session-${user.username}` } };
}
