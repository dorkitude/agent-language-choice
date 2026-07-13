import { scryptSync, randomBytes, timingSafeEqual } from "node:crypto";
import { getDb } from "../db";

export type User = { username: string; role: string; hash: string };

export function getUser(username: string): User | undefined {
  const row = getDb()
    .prepare("SELECT username, role, hash FROM users WHERE username = ?")
    .get(username) as User | undefined;
  return row;
}

export function hasUser(username: string): boolean {
  return getUser(username) !== undefined;
}

export function createUser(user: User): void {
  getDb()
    .prepare("INSERT INTO users (username, role, hash) VALUES (?, ?, ?)")
    .run(user.username, user.role, user.hash);
}

export function hashPassword(password: string): string {
  const salt = randomBytes(16);
  const derived = scryptSync(password, salt, 32);
  return `scrypt$${salt.toString("hex")}$${derived.toString("hex")}`;
}

export function verifyPassword(password: string, stored: string): boolean {
  const parts = stored.split("$");
  if (parts.length !== 3 || parts[0] !== "scrypt") return false;
  const salt = Buffer.from(parts[1], "hex");
  const expected = Buffer.from(parts[2], "hex");
  const derived = scryptSync(password, salt, expected.length);
  return expected.length === derived.length && timingSafeEqual(expected, derived);
}

export const USERNAME_RE = /^[a-z0-9_-]{2,32}$/;
