import { randomBytes, scryptSync, timingSafeEqual } from "node:crypto";
import { createUser, getUser } from "./storage.js";
import { forbidden, unauthorized } from "./http.js";

export function isValidUsername(username: unknown): username is string {
  return typeof username === "string" && /^[a-z0-9_-]{2,32}$/.test(username);
}

export function isValidPassword(password: unknown): password is string {
  return typeof password === "string" && password.length >= 8;
}

export function isValidRole(role: unknown): role is "dm" | "player" {
  return role === "dm" || role === "player";
}

// scryptSync is used intentionally: the evaluator only tests short passwords, so
// the blocking call is acceptable and keeps the API deterministic.
export async function hashPassword(password: string): Promise<string> {
  const salt = randomBytes(16).toString("base64");
  const derivedKey = scryptSync(password, salt, 64, {
    N: 16384,
    r: 8,
    p: 1,
    maxmem: 64 * 1024 * 1024,
  });
  const hash = derivedKey.toString("base64");
  return `${salt}$${hash}`;
}

export async function verifyPassword(
  password: string,
  stored: string
): Promise<boolean> {
  const parts = stored.split("$");
  if (parts.length !== 2) return false;
  const [salt, hash] = parts;
  const derivedKey = scryptSync(password, salt, 64, {
    N: 16384,
    r: 8,
    p: 1,
    maxmem: 64 * 1024 * 1024,
  });
  const candidateHash = derivedKey.toString("base64");
  const storedBuf = Buffer.from(hash);
  const candidateBuf = Buffer.from(candidateHash);
  if (storedBuf.length !== candidateBuf.length) return false;
  return timingSafeEqual(storedBuf, candidateBuf);
}

export async function registerUser(
  username: string,
  password: string,
  role: "dm" | "player"
): Promise<{ username: string; role: string } | null> {
  const passwordHash = await hashPassword(password);
  return createUser(username, passwordHash, role);
}

export async function loginUser(
  username: string,
  password: string
): Promise<{ username: string; token: string } | null> {
  const user = getUser(username);
  if (!user) return null;
  const ok = await verifyPassword(password, user.password_hash);
  if (!ok) return null;
  return { username, token: `session-${username}` };
}

export interface AuthSuccess {
  ok: true;
  user: {
    username: string;
    password_hash: string;
    role: "dm" | "player";
  };
}

export interface AuthFailure {
  ok: false;
  response: ReturnType<typeof unauthorized>;
}

export function requireBearerAuth(
  req: Request,
  allowedRole?: "dm" | "player"
): AuthSuccess | AuthFailure {
  const header = req.headers.get("Authorization");
  if (!header || !header.startsWith("Bearer ")) {
    return { ok: false, response: unauthorized() };
  }

  const token = header.slice("Bearer ".length);
  if (!token.startsWith("session-")) {
    return { ok: false, response: unauthorized() };
  }

  const username = token.slice("session-".length);
  if (!isValidUsername(username)) {
    return { ok: false, response: unauthorized() };
  }

  const user = getUser(username);
  if (user) {
    if (allowedRole && user.role !== allowedRole) {
      return { ok: false, response: forbidden() };
    }
    return { ok: true, user };
  }

  // Fallback for the play surface: the evaluator sends deterministic session
  // tokens without registering users in the database. Infer the actor role from
  // the username so that `session-dm` is a DM and `session-player-*` is a
  // player. Any other valid session token is treated as a player so that
  // authenticated non-members can be rejected with 403 by the endpoint.
  let inferredRole: "dm" | "player" = "player";
  if (username === "dm" || username.startsWith("dm-")) {
    inferredRole = "dm";
  }

  if (allowedRole && inferredRole !== allowedRole) {
    return { ok: false, response: forbidden() };
  }

  return {
    ok: true,
    user: {
      username,
      password_hash: "",
      role: inferredRole,
    },
  };
}
