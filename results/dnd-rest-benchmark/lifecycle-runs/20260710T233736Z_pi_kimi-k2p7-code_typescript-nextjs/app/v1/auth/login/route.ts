import { loginUser } from "../../../lib/auth.js";

export async function POST(request: Request) {
  try {
    const body = (await request.json()) as Record<string, unknown>;
    const user = await loginUser(body.username, body.password);
    return Response.json({
      username: user.username,
      token: `session-${user.username}`,
    });
  } catch (error) {
    if (error instanceof SyntaxError) {
      return Response.json({ error: "invalid json" }, { status: 400 });
    }
    const message = error instanceof Error ? error.message : "invalid request";
    if (message === "invalid credentials") {
      return Response.json({ error: message }, { status: 401 });
    }
    return Response.json({ error: message }, { status: 400 });
  }
}
