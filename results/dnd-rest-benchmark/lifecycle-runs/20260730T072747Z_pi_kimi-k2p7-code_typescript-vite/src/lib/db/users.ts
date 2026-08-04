// User account persistence.

import { db } from './connection.js';
import type { User, UserRole } from '../types.js';

export function createUser(username: string, role: UserRole, passwordHash: string): void {
  db.prepare('INSERT INTO users (username, role, password_hash) VALUES (?, ?, ?)').run(username, role, passwordHash);
}

export function getUser(username: string): User | undefined {
  const row = db.prepare('SELECT username, role, password_hash FROM users WHERE username = ?').get(username) as
    | { username: string; role: UserRole; password_hash: string }
    | undefined;
  if (!row) return undefined;
  return { username: row.username, role: row.role, passwordHash: row.password_hash };
}

export function userExists(username: string): boolean {
  const row = db.prepare('SELECT 1 FROM users WHERE username = ?').get(username) as { '1': number } | undefined;
  return row !== undefined;
}
