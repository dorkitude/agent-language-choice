import { badRequest, isRecord, json, readJson } from "../../../api.js";
import { hashPassword, isValidPassword, isValidRole, isValidUsername, users } from "../users.js";

export const runtime = "nodejs";

export async function POST(request: Request) {
  const body = await readJson(request);
  if (
    !isRecord(body) ||
    !isValidUsername(body.username) ||
    !isValidPassword(body.password) ||
    !isValidRole(body.role)
  ) {
    return badRequest();
  }

  if (users.has(body.username)) {
    return json({ error: "duplicate_username" }, 409);
  }

  users.set(body.username, {
    username: body.username,
    role: body.role,
    passwordHash: hashPassword(body.password),
  });

  return json({
    username: body.username,
    role: body.role,
  }, 201);
}
