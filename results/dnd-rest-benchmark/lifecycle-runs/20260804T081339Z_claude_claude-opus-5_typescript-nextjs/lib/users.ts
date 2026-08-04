import { randomBytes, scryptSync, timingSafeEqual } from "node:crypto";

import { database } from "./db";

export const ROLES = ["dm", "player"] as const;

export type Role = (typeof ROLES)[number];

export type User = { username: string; role: Role; salt: string; hash: string };

const KEY_LENGTH = 32;

/** Users are durable: they live in the `users` table of the SQLite database. */
function loadUser(username: string): User | undefined {
  const row = database()
    .prepare("SELECT username, role, salt, hash FROM users WHERE username = ?")
    .get(username) as Record<string, string> | undefined;
  if (!row) return undefined;
  return {
    username: row.username!,
    role: row.role as Role,
    salt: row.salt!,
    hash: row.hash!,
  };
}

/** Password hashing is isolated here so a different KDF can drop straight in. */
function hashPassword(password: string, salt: string): string {
  return scryptSync(password, salt, KEY_LENGTH).toString("hex");
}

export function isValidUsername(value: unknown): value is string {
  return typeof value === "string" && /^[a-z0-9_-]{2,32}$/.test(value);
}

export function isValidPassword(value: unknown): value is string {
  return typeof value === "string" && value.length >= 8;
}

export function isValidRole(value: unknown): value is Role {
  return value === "dm" || value === "player";
}

export function hasUser(username: string): boolean {
  return loadUser(username) !== undefined;
}

export function createUser(username: string, password: string, role: Role): User {
  const salt = randomBytes(16).toString("hex");
  const user: User = { username, role, salt, hash: hashPassword(password, salt) };
  database()
    .prepare("INSERT INTO users (username, role, salt, hash) VALUES (?, ?, ?, ?)")
    .run(user.username, user.role, user.salt, user.hash);
  return user;
}

/** Verify credentials, returning the user only on an exact password match. */
export function verifyUser(username: string, password: string): User | undefined {
  const user = loadUser(username);
  if (!user) return undefined;
  const candidate = Buffer.from(hashPassword(password, user.salt), "hex");
  const expected = Buffer.from(user.hash, "hex");
  if (candidate.length !== expected.length) return undefined;
  return timingSafeEqual(candidate, expected) ? user : undefined;
}

export function sessionToken(username: string): string {
  return `session-${username}`;
}
