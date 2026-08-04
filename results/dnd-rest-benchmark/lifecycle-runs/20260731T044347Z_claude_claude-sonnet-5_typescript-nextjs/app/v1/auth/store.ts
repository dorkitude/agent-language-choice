import { randomBytes, scryptSync, timingSafeEqual } from "node:crypto";
import { getDb } from "../db.js";

export interface User {
  username: string;
  passwordHash: string;
  role: "dm" | "player";
}

export function hasUser(username: string): boolean {
  const row = getDb()
    .prepare("SELECT username FROM users WHERE username = ?")
    .get(username);
  return row !== undefined;
}

export function getUser(username: string): User | undefined {
  const row = getDb()
    .prepare("SELECT username, password_hash, role FROM users WHERE username = ?")
    .get(username) as { username: string; password_hash: string; role: string } | undefined;

  if (!row) return undefined;

  return {
    username: row.username,
    passwordHash: row.password_hash,
    role: row.role as "dm" | "player",
  };
}

export function createUser(username: string, password: string, role: "dm" | "player"): User {
  const user: User = { username, passwordHash: hashPassword(password), role };
  getDb()
    .prepare("INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)")
    .run(user.username, user.passwordHash, user.role);
  return user;
}

// Stored hash format is "<saltHex>:<derivedKeyHex>", where the derived key
// length equals whatever scryptSync produced at hash time (64 bytes below).
// verifyPassword derives against the stored salt using the length of the
// stored derived key, so this format tolerates future changes to the derived
// key length without a migration, as long as ":" continues to separate the
// two hex segments.
export function hashPassword(password: string): string {
  const salt = randomBytes(16);
  const derived = scryptSync(password, salt, 64);
  return `${salt.toString("hex")}:${derived.toString("hex")}`;
}

export function verifyPassword(password: string, storedHash: string): boolean {
  const [saltHex, derivedHex] = storedHash.split(":");
  if (!saltHex || !derivedHex) return false;
  const salt = Buffer.from(saltHex, "hex");
  const expected = Buffer.from(derivedHex, "hex");
  const actual = scryptSync(password, salt, expected.length);
  // Compare with timingSafeEqual (not ===) to avoid leaking hash equality
  // via response-time side channels.
  return actual.length === expected.length && timingSafeEqual(actual, expected);
}
