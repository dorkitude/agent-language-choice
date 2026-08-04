import { createUser, hasUser } from "../store.js";
import { parseJsonBody } from "../../http.js";

const USERNAME_RE = /^[a-z0-9_-]{2,32}$/;

export async function POST(request: Request) {
  const parsed = await parseJsonBody(request);
  if (!parsed.ok) return parsed.response;
  const body = parsed.body;

  const { username, password, role } = (body ?? {}) as {
    username?: unknown;
    password?: unknown;
    role?: unknown;
  };

  if (typeof username !== "string" || !USERNAME_RE.test(username)) {
    return Response.json(
      { error: "username must be 2-32 characters of lowercase letters, digits, _, or -" },
      { status: 400 },
    );
  }

  if (typeof password !== "string" || password.length < 8) {
    return Response.json(
      { error: "password must be at least 8 characters" },
      { status: 400 },
    );
  }

  if (role !== "dm" && role !== "player") {
    return Response.json({ error: "role must be dm or player" }, { status: 400 });
  }

  if (hasUser(username)) {
    return Response.json({ error: `username ${username} already exists` }, { status: 409 });
  }

  const user = createUser(username, password, role);

  return Response.json({ username: user.username, role: user.role }, { status: 201 });
}
