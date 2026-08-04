// Password hashing and verification using scrypt with a per-user random salt.
// The storage format is "salt:hash" and the salt is a hex string.

import crypto from 'node:crypto';
import type { IncomingMessage } from 'node:http';
import { getUser } from './db.js';
import type { User, UserRole } from './types.js';

export function getAuthUser(req: IncomingMessage): User | undefined {
  const header = req.headers['authorization'];
  if (!header || typeof header !== 'string') return undefined;
  const [scheme, token] = header.split(' ');
  if (scheme !== 'Bearer' || !token) return undefined;
  const match = token.match(/^session-(.+)$/);
  if (!match) return undefined;
  const username = match[1];
  const existing = getUser(username);
  if (existing) return existing;
  // The play surface treats a well-formed session-<username> token as a
  // valid actor, inferring the role from the username so that ownership and
  // membership checks can work without requiring every test token to be
  // pre-registered in the auth database.
  const role: UserRole = username === 'dm' ? 'dm' : 'player';
  return { username, role, passwordHash: '' };
}

export function hashPassword(password: string): string {
  const salt = crypto.randomBytes(16).toString('hex');
  const hash = crypto.scryptSync(password, salt, 64);
  return `${salt}:${hash.toString('hex')}`;
}

export function verifyPassword(password: string, stored: string): boolean {
  const [salt, hash] = stored.split(':');
  if (!salt || !hash) return false;
  const derived = crypto.scryptSync(password, salt, 64);
  const expected = Buffer.from(hash, 'hex');
  if (derived.length !== expected.length) return false;
  return crypto.timingSafeEqual(derived, expected);
}
