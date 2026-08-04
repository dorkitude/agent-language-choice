import { badRequest, conflict, json, readObject } from "../../../../lib/http";
import {
  createUser,
  hasUser,
  isValidPassword,
  isValidRole,
  isValidUsername,
} from "../../../../lib/users";

export const dynamic = "force-dynamic";

export async function POST(request: Request): Promise<Response> {
  const body = await readObject(request);
  if (!body) return badRequest("body must be a JSON object");

  const { username, password, role } = body;
  if (!isValidUsername(username)) {
    return badRequest("username must be 2-32 characters of [a-z0-9_-]");
  }
  if (!isValidPassword(password)) {
    return badRequest("password must be at least 8 characters");
  }
  if (!isValidRole(role)) return badRequest("role must be 'dm' or 'player'");

  if (hasUser(username)) return conflict("username already exists");

  const user = createUser(username, password, role);
  return json({ username: user.username, role: user.role }, 201);
}
