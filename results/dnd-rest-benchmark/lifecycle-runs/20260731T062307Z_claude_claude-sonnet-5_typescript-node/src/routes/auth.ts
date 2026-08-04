// User registration and login. Passwords are stored as `salt:hash` scrypt
// digests; tokens are a placeholder (`session-<username>`) — there is no
// real session store or expiry, matching the rest of this API's scope.
import type { ServerResponse } from "node:http";
import { randomBytes, scryptSync, timingSafeEqual } from "node:crypto";
import { db } from "../db.js";
import { sendJson } from "../http.js";
import { isPlainObject } from "../validation.js";

function hashPassword(password: string): string {
  const salt = randomBytes(16);
  const derived = scryptSync(password, salt, 64);
  return `${salt.toString("hex")}:${derived.toString("hex")}`;
}

function verifyPassword(password: string, stored: string): boolean {
  const [saltHex, hashHex] = stored.split(":");
  if (!saltHex || !hashHex) return false;
  const salt = Buffer.from(saltHex, "hex");
  const expected = Buffer.from(hashHex, "hex");
  const derived = scryptSync(password, salt, expected.length);
  return derived.length === expected.length && timingSafeEqual(derived, expected);
}

interface User {
  username: string;
  role: "dm" | "player";
  passwordHash: string;
}

function getUser(username: string): User | undefined {
  const row = db.prepare("SELECT username, role, password_hash FROM users WHERE username = ?").get(username) as
    | { username: string; role: "dm" | "player"; password_hash: string }
    | undefined;
  if (!row) return undefined;
  return { username: row.username, role: row.role, passwordHash: row.password_hash };
}

function saveUser(user: User): void {
  db.prepare("INSERT INTO users (username, role, password_hash) VALUES (?, ?, ?)").run(
    user.username,
    user.role,
    user.passwordHash,
  );
}

function hasUser(username: string): boolean {
  const row = db.prepare("SELECT 1 FROM users WHERE username = ?").get(username);
  return row !== undefined;
}

const USERNAME_RE = /^[a-z0-9_-]{2,32}$/;

export function handleRegister(res: ServerResponse, body: unknown): void {
  if (
    !isPlainObject(body) ||
    typeof body.username !== "string" ||
    typeof body.password !== "string" ||
    typeof body.role !== "string"
  ) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  if (!USERNAME_RE.test(body.username)) {
    sendJson(res, 400, { error: "invalid username" });
    return;
  }

  if (body.password.length < 8) {
    sendJson(res, 400, { error: "invalid password" });
    return;
  }

  if (body.role !== "dm" && body.role !== "player") {
    sendJson(res, 400, { error: "invalid role" });
    return;
  }

  if (hasUser(body.username)) {
    sendJson(res, 409, { error: "username already exists" });
    return;
  }

  const user: User = {
    username: body.username,
    role: body.role,
    passwordHash: hashPassword(body.password),
  };
  saveUser(user);

  sendJson(res, 201, { username: user.username, role: user.role });
}

export function handleLogin(res: ServerResponse, body: unknown): void {
  if (!isPlainObject(body) || typeof body.username !== "string" || typeof body.password !== "string") {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  const user = getUser(body.username);
  if (!user || !verifyPassword(body.password, user.passwordHash)) {
    sendJson(res, 401, { error: "invalid credentials" });
    return;
  }

  sendJson(res, 200, { username: user.username, token: `session-${user.username}` });
}
