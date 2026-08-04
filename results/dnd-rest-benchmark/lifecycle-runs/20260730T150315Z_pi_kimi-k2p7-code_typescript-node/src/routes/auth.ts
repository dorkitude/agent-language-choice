import { randomBytes, scryptSync, timingSafeEqual } from 'node:crypto';
import { ServerResponse } from 'node:http';
import { sendJSON } from '../http-utils.js';
import { createUser, getUser, userExists } from '../repository.js';
import { isValidPassword, isValidRole, isValidUsername } from '../validators.js';

function hashPassword(password: string): { salt: string; hash: string } {
  const salt = randomBytes(16);
  const hash = scryptSync(password, salt, 64);
  return { salt: salt.toString('hex'), hash: hash.toString('hex') };
}

function verifyPassword(password: string, saltHex: string, hashHex: string): boolean {
  try {
    const salt = Buffer.from(saltHex, 'hex');
    const expected = Buffer.from(hashHex, 'hex');
    const actual = scryptSync(password, salt, expected.length);
    return timingSafeEqual(actual, expected);
  } catch {
    return false;
  }
}

export function handleRegister(res: ServerResponse, _params: unknown, body: unknown): void {
  const { username, password, role } = body as Record<string, unknown>;
  if (!isValidUsername(username) || !isValidPassword(password) || !isValidRole(role)) {
    sendJSON(res, 400, { error: 'invalid input' });
    return;
  }
  if (userExists(username)) {
    sendJSON(res, 409, { error: 'username taken' });
    return;
  }
  const { salt, hash } = hashPassword(password);
  createUser({ username, role, salt, hash });
  sendJSON(res, 201, { username, role });
}

export function handleLogin(res: ServerResponse, _params: unknown, body: unknown): void {
  const { username, password } = body as Record<string, unknown>;
  if (!isValidUsername(username) || typeof password !== 'string') {
    sendJSON(res, 400, { error: 'invalid input' });
    return;
  }
  const user = getUser(username);
  if (!user || !verifyPassword(password, user.salt, user.hash)) {
    sendJSON(res, 401, { error: 'invalid credentials' });
    return;
  }
  sendJSON(res, 200, { username: user.username, token: `session-${user.username}` });
}
