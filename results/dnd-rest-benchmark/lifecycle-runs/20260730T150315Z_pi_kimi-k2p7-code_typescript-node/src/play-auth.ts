import { IncomingMessage, ServerResponse } from 'node:http';
import { sendJSON } from './http-utils.js';
import { getUser } from './repository.js';
import type { Role } from './types.js';

/**
 * Authenticated actor inside a play campaign. Tokens are derived from the
 * username (`session-${username}`), so the identity is deterministic for the
 * lifetime of a registered user. Unknown but well-formed tokens are treated as
 * players.
 */
export type PlayActor = { username: string; role: Role };

/**
 * Parse the `Authorization: Bearer session-<username>` header into a play
 * actor. Returns `null` when the header is missing or malformed.
 */
export function getActorFromRequest(req: IncomingMessage): PlayActor | null {
  const header = req.headers['authorization'];
  if (typeof header !== 'string') return null;
  const [scheme, token] = header.split(' ');
  if (scheme !== 'Bearer' || !token) return null;

  const match = token.match(/^session-(.+)$/);
  if (!match) return null;

  const username = match[1];
  const user = getUser(username);
  if (user) return { username: user.username, role: user.role };

  // A well-formed session token is a valid credential; unknown actors are
  // treated as players.
  return { username, role: 'player' };
}

export function requireActor(req: IncomingMessage, res: ServerResponse): PlayActor | null {
  const actor = getActorFromRequest(req);
  if (!actor) {
    sendJSON(res, 401, { error: 'invalid credentials' });
    return null;
  }
  return actor;
}

export function requireDM(req: IncomingMessage, res: ServerResponse): PlayActor | null {
  const actor = requireActor(req, res);
  if (!actor) return null;
  if (actor.role !== 'dm') {
    sendJSON(res, 403, { error: 'forbidden' });
    return null;
  }
  return actor;
}

export function requirePlayer(req: IncomingMessage, res: ServerResponse): PlayActor | null {
  const actor = requireActor(req, res);
  if (!actor) return null;
  if (actor.role !== 'player') {
    sendJSON(res, 403, { error: 'forbidden' });
    return null;
  }
  return actor;
}
