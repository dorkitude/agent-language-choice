import type { ServerResponse } from 'node:http';
import { sendError, sendJson } from '../http.js';
import { createUser, getUser, userExists } from '../db.js';
import { hashPassword, verifyPassword } from '../auth.js';
import { isValidRole, USERNAME_RE } from '../validation.js';

export function handleRegister(body: unknown, res: ServerResponse): boolean {
  const b = body as any;
  if (!b || typeof b.username !== 'string' || typeof b.password !== 'string' || !isValidRole(b.role)) {
    sendError(res, 400, 'invalid request');
    return true;
  }
  if (!USERNAME_RE.test(b.username)) {
    sendError(res, 400, 'invalid username');
    return true;
  }
  if (b.password.length < 8) {
    sendError(res, 400, 'invalid password');
    return true;
  }
  if (userExists(b.username)) {
    sendError(res, 409, 'username already exists');
    return true;
  }
  createUser(b.username, b.role, hashPassword(b.password));
  sendJson(res, 201, { username: b.username, role: b.role });
  return true;
}

export function handleLogin(body: unknown, res: ServerResponse): boolean {
  const b = body as any;
  if (!b || typeof b.username !== 'string' || typeof b.password !== 'string') {
    sendError(res, 400, 'invalid request');
    return true;
  }
  const user = getUser(b.username);
  if (!user || !verifyPassword(b.password, user.passwordHash)) {
    sendError(res, 401, 'invalid credentials');
    return true;
  }
  sendJson(res, 200, { username: user.username, token: `session-${user.username}` });
  return true;
}
