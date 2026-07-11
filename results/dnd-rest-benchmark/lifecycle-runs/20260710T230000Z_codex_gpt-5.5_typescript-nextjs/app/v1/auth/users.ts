import { randomBytes, scryptSync, timingSafeEqual } from "node:crypto";
import { db } from "../storage/db.js";

export type Role = "dm" | "player";

export type User = {
  username: string;
  role: Role;
  passwordHash: string;
};

const SCRYPT_KEY_LENGTH = 64;

export const users = {
  get(username: string): User | undefined {
    const row = db()
      .prepare("SELECT username, role, password_hash FROM users WHERE username = ?")
      .get(username);

    if (
      row === undefined ||
      typeof row.username !== "string" ||
      (row.role !== "dm" && row.role !== "player") ||
      typeof row.password_hash !== "string"
    ) {
      return undefined;
    }

    return {
      username: row.username,
      role: row.role,
      passwordHash: row.password_hash,
    };
  },

  has(username: string): boolean {
    return this.get(username) !== undefined;
  },

  set(username: string, user: User): void {
    db()
      .prepare("INSERT INTO users (username, role, password_hash) VALUES (?, ?, ?)")
      .run(username, user.role, user.passwordHash);
  },
};

export function isValidUsername(value: unknown): value is string {
  return typeof value === "string" && /^[a-z0-9_-]{2,32}$/.test(value);
}

export function isValidPassword(value: unknown): value is string {
  return typeof value === "string" && value.length >= 8;
}

export function isValidRole(value: unknown): value is Role {
  return value === "dm" || value === "player";
}

export function hashPassword(password: string): string {
  const salt = randomBytes(16).toString("hex");
  const hash = scryptSync(password, salt, SCRYPT_KEY_LENGTH).toString("hex");
  return `${salt}:${hash}`;
}

export function verifyPassword(password: string, storedHash: string): boolean {
  const [salt, expectedHex] = storedHash.split(":");
  if (!salt || !expectedHex) {
    return false;
  }

  const expected = Buffer.from(expectedHex, "hex");
  const actual = scryptSync(password, salt, expected.length);
  return expected.length === actual.length && timingSafeEqual(expected, actual);
}
