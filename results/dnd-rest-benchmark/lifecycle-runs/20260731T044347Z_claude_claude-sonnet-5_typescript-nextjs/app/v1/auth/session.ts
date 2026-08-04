import { getUser, User } from "./store.js";

export type SessionResult = { ok: true; user: User } | { ok: false; response: Response };

const BEARER_PREFIX = "Bearer session-";

export function requireSession(request: Request): SessionResult {
  const header = request.headers.get("authorization") ?? request.headers.get("Authorization");

  if (!header || !header.startsWith(BEARER_PREFIX)) {
    return {
      ok: false,
      response: Response.json({ error: "missing or invalid credentials" }, { status: 401 }),
    };
  }

  const username = header.slice(BEARER_PREFIX.length);

  if (username.length === 0) {
    return {
      ok: false,
      response: Response.json({ error: "missing or invalid credentials" }, { status: 401 }),
    };
  }

  const user = getUser(username);

  if (!user) {
    return {
      ok: false,
      response: Response.json({ error: "not a campaign member" }, { status: 403 }),
    };
  }

  return { ok: true, user };
}
