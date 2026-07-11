import { registerUser } from "../../../lib/auth.js";

export async function POST(request: Request) {
  try {
    const body = (await request.json()) as Record<string, unknown>;
    const user = await registerUser(body);
    return Response.json({ username: user.username, role: user.role }, { status: 201 });
  } catch (error) {
    if (error instanceof SyntaxError) {
      return Response.json({ error: "invalid json" }, { status: 400 });
    }
    const message = error instanceof Error ? error.message : "invalid request";
    if (message === "username already exists") {
      return Response.json({ error: message }, { status: 409 });
    }
    return Response.json({ error: message }, { status: 400 });
  }
}
