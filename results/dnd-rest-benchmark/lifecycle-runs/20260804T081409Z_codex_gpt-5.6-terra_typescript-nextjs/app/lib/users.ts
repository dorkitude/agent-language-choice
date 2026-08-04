import { pbkdf2Sync, randomBytes, timingSafeEqual } from "node:crypto";
import { database } from "./storage";

type User = {
  role: "dm" | "player";
  salt: string;
  passwordHash: string;
};

const HASH_ITERATIONS = 100_000;
const HASH_LENGTH = 32;

function hashPassword(password: string, salt: string): Buffer {
  return pbkdf2Sync(password, salt, HASH_ITERATIONS, HASH_LENGTH, "sha256");
}

export function createUser(username: string, password: string, role: "dm" | "player"): boolean {
  const existing = database.prepare("SELECT 1 FROM users WHERE username = ?").get(username);
  if (existing) return false;

  const salt = randomBytes(16).toString("hex");
  database.prepare("INSERT INTO users (username, role, salt, password_hash) VALUES (?, ?, ?, ?)").run(
    username, role, salt, hashPassword(password, salt).toString("hex"),
  );
  return true;
}

export function authenticateUser(username: string, password: string): boolean {
  const user = database.prepare("SELECT role, salt, password_hash AS passwordHash FROM users WHERE username = ?").get(username) as User | undefined;
  if (!user) return false;

  const expected = Buffer.from(user.passwordHash, "hex");
  const actual = hashPassword(password, user.salt);
  return expected.length === actual.length && timingSafeEqual(expected, actual);
}
