import { scryptSync, randomBytes, timingSafeEqual } from 'node:crypto';

export const USERNAME_RE = /^[a-z0-9_-]{2,32}$/;

export function hashPassword(password) {
  const salt = randomBytes(16);
  const hash = scryptSync(password, salt, 64);
  return `${salt.toString('hex')}:${hash.toString('hex')}`;
}

export function verifyPassword(password, stored) {
  const [saltHex, hashHex] = stored.split(':');
  const salt = Buffer.from(saltHex, 'hex');
  const expected = Buffer.from(hashHex, 'hex');
  const actual = scryptSync(password, salt, 64);
  if (actual.length !== expected.length) return false;
  return timingSafeEqual(actual, expected);
}

const SESSION_TOKEN_RE = /^session-([a-z0-9_-]{2,32})$/;

// Extracts the username claimed by an `Authorization: Bearer session-<username>`
// header. Returns null if the header is missing or malformed; does not
// verify the username exists.
export function bearerUsername(req) {
  const header = req.headers['authorization'];
  if (typeof header !== 'string') return null;
  const match = /^Bearer (.+)$/.exec(header);
  if (!match) return null;
  const tokenMatch = SESSION_TOKEN_RE.exec(match[1]);
  return tokenMatch ? tokenMatch[1] : null;
}
