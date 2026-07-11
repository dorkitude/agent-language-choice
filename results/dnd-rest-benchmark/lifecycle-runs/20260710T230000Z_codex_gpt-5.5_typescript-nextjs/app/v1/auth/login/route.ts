import { badRequest, isRecord, json, readJson } from "../../../api.js";
import { users, verifyPassword } from "../users.js";

export const runtime = "nodejs";

export async function POST(request: Request) {
  const body = await readJson(request);
  if (!isRecord(body) || typeof body.username !== "string" || typeof body.password !== "string") {
    return badRequest();
  }

  const user = users.get(body.username);
  if (!user || !verifyPassword(body.password, user.passwordHash)) {
    return json({ error: "bad_credentials" }, 401);
  }

  return json({
    username: user.username,
    token: `session-${user.username}`,
  });
}
