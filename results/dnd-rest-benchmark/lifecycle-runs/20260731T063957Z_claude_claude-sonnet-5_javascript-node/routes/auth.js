import { sendJson, parseJsonBody } from '../lib/http.js';
import { users } from '../lib/stores.js';
import { USERNAME_RE, hashPassword, verifyPassword } from '../lib/auth.js';

export function registerAuthRoutes(router) {
  router.post('/v1/auth/register', async (req, res) => {
    const body = await parseJsonBody(req, res);
    if (!body.ok) return;
    const username = body.data && body.data.username;
    const password = body.data && body.data.password;
    const role = body.data && body.data.role;
    if (
      typeof username !== 'string' ||
      !USERNAME_RE.test(username) ||
      typeof password !== 'string' ||
      password.length < 8 ||
      (role !== 'dm' && role !== 'player')
    ) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }
    if (users.has(username)) {
      sendJson(res, 409, { error: 'username already exists' });
      return;
    }
    users.set(username, { username, role, passwordHash: hashPassword(password) });
    sendJson(res, 201, { username, role });
  });

  router.post('/v1/auth/login', async (req, res) => {
    const body = await parseJsonBody(req, res);
    if (!body.ok) return;
    const username = body.data && body.data.username;
    const password = body.data && body.data.password;
    if (typeof username !== 'string' || typeof password !== 'string') {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }
    const user = users.get(username);
    if (!user || !verifyPassword(password, user.passwordHash)) {
      sendJson(res, 401, { error: 'invalid credentials' });
      return;
    }
    sendJson(res, 200, { username, token: `session-${username}` });
  });
}
