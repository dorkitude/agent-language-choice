/**
 * User account repository.
 */

import { getDb } from "./core.js";
import type { CreateUserResult, StoredUser } from "../types.js";

export function getUser(username: string): StoredUser | null {
  const database = getDb();
  const row = database
    .prepare("SELECT username, password_hash, role FROM users WHERE username = ?")
    .get(username) as
    | { username: string; password_hash: string; role: "dm" | "player" }
    | undefined;
  return row || null;
}

export function createUser(
  username: string,
  passwordHash: string,
  role: "dm" | "player"
): CreateUserResult | null {
  const database = getDb();
  try {
    database
      .prepare(
        "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)"
      )
      .run(username, passwordHash, role);
    return { username, role };
  } catch {
    return null;
  }
}
