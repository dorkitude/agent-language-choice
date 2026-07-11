import { randomBytes, scryptSync, timingSafeEqual } from "node:crypto";

export type User = { username: string; role: "dm" | "player"; hash: string };

type AuthStore = { users: Map<string, User> };

const g = globalThis as unknown as { __authStore?: AuthStore };

export function authStore(): AuthStore {
  if (!g.__authStore) {
    g.__authStore = { users: new Map() };
  }
  return g.__authStore;
}

const USERNAME_RE = /^[a-z0-9_-]{2,32}$/;

export function validUsername(u: unknown): u is string {
  return typeof u === "string" && USERNAME_RE.test(u);
}

export function validPassword(p: unknown): p is string {
  return typeof p === "string" && p.length >= 8;
}

export function validRole(r: unknown): r is "dm" | "player" {
  return r === "dm" || r === "player";
}

// Password hashing isolated behind this helper. Uses Node's built-in scrypt.
export function hashPassword(password: string): string {
  const salt = randomBytes(16);
  const derived = scryptSync(password, salt, 64);
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
