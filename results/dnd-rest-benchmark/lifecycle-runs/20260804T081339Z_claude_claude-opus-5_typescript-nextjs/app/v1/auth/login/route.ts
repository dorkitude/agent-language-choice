import { badRequest, json, readObject, unauthorized } from "../../../../lib/http";
import { sessionToken, verifyUser } from "../../../../lib/users";

export const dynamic = "force-dynamic";

export async function POST(request: Request): Promise<Response> {
  const body = await readObject(request);
  if (!body) return badRequest("body must be a JSON object");

  const { username, password } = body;
  if (typeof username !== "string" || typeof password !== "string") {
    return badRequest("username and password must be strings");
  }

  const user = verifyUser(username, password);
  if (!user) return unauthorized("invalid username or password");

  return json({ username: user.username, token: sessionToken(user.username) });
}
