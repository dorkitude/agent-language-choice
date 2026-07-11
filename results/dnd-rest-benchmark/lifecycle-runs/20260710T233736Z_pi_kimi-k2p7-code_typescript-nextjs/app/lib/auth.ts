import crypto from "node:crypto";
import { getDb } from "./db.js";

const USERNAME_RE = /^[a-z0-9_-]{2,32}$/;
const ROLES = ["dm", "player"] as const;
export type Role = (typeof ROLES)[number];

const SCRYPT_OPTIONS = {
  N: 16384,
  r: 16,
  p: 1,
  maxmem: 64 * 1024 * 1024,
};
const KEYLEN = 64;

export function validateUsername(username: unknown): string {
  if (typeof username !== "string") {
    throw new Error("username must be a string");
  }
  if (!USERNAME_RE.test(username)) {
    throw new Error("username must be 2-32 lowercase letters, digits, _, or -");
  }
  return username;
}

export function validatePassword(password: unknown): string {
  if (typeof password !== "string") {
    throw new Error("password must be a string");
  }
  if (password.length < 8) {
    throw new Error("password must be at least 8 characters");
  }
  return password;
}

export function validateRole(role: unknown): Role {
  if (role !== "dm" && role !== "player") {
    throw new Error("role must be dm or player");
  }
  return role;
}

export async function hashPassword(
  password: string
): Promise<{ hash: string; salt: string }> {
  const salt = crypto.randomBytes(32).toString("hex");
  const hash = await new Promise<Buffer>((resolve, reject) => {
    crypto.scrypt(
      password,
      salt,
      KEYLEN,
      SCRYPT_OPTIONS,
      (err, derivedKey) => {
        if (err) reject(err);
        else resolve(derivedKey);
      }
    );
  });
  return { hash: hash.toString("hex"), salt };
}

export async function verifyPassword(
  password: string,
  salt: string,
  hash: string
): Promise<boolean> {
  const derivedKey = await new Promise<Buffer>((resolve, reject) => {
    crypto.scrypt(password, salt, KEYLEN, SCRYPT_OPTIONS, (err, key) => {
      if (err) reject(err);
      else resolve(key);
    });
  });
  const storedHash = Buffer.from(hash, "hex");
  if (storedHash.length !== derivedKey.length) return false;
  return crypto.timingSafeEqual(storedHash, derivedKey);
}

export async function registerUser(
  input: Record<string, unknown>
): Promise<{ username: string; role: Role }> {
  const username = validateUsername(input.username);
  const password = validatePassword(input.password);
  const role = validateRole(input.role);

  const db = getDb();
  const existing = db
    .prepare("SELECT username FROM users WHERE username = ?")
    .get(username);
  if (existing) {
    throw new Error("username already exists");
  }

  const { hash, salt } = await hashPassword(password);
  db.prepare(
    "INSERT INTO users (username, password_hash, salt, role) VALUES (?, ?, ?, ?)"
  ).run(username, hash, salt, role);

  return { username, role };
}

export async function loginUser(
  username: unknown,
  password: unknown
): Promise<{ username: string; role: Role }> {
  if (typeof username !== "string" || typeof password !== "string") {
    throw new Error("username and password must be strings");
  }

  const db = getDb();
  const row = db
    .prepare(
      "SELECT username, password_hash, salt, role FROM users WHERE username = ?"
    )
    .get(username) as
    | { username: string; password_hash: string; salt: string; role: Role }
    | undefined;
  if (!row) {
    throw new Error("invalid credentials");
  }

  const valid = await verifyPassword(password, row.salt, row.password_hash);
  if (!valid) {
    throw new Error("invalid credentials");
  }

  return { username: row.username, role: row.role };
}
