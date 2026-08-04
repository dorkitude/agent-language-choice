import { getUser, verifyPassword } from "../store.js";
import { parseJsonBody, requireNonEmptyString } from "../../http.js";

export async function POST(request: Request) {
  const parsed = await parseJsonBody(request);
  if (!parsed.ok) return parsed.response;
  const body = parsed.body;

  const { username, password } = (body ?? {}) as {
    username?: unknown;
    password?: unknown;
  };

  const validUsername = requireNonEmptyString(username, "username");
  if (validUsername instanceof Response) return validUsername;

  const validPassword = requireNonEmptyString(password, "password");
  if (validPassword instanceof Response) return validPassword;

  const user = getUser(validUsername);

  if (!user || !verifyPassword(validPassword, user.passwordHash)) {
    return Response.json({ error: "invalid username or password" }, { status: 401 });
  }

  return Response.json({ username: user.username, token: `session-${user.username}` });
}
