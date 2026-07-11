import { NextResponse } from "next/server";
import { authStore, verifyPassword } from "../../../lib/auth";

export async function POST(req: Request) {
  let body: unknown;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "invalid JSON" }, { status: 400 });
  }

  const obj =
    body && typeof body === "object" ? (body as Record<string, unknown>) : {};
  const { username, password } = obj;

  if (typeof username !== "string" || typeof password !== "string") {
    return NextResponse.json({ error: "invalid credentials" }, { status: 400 });
  }

  const s = authStore();
  const user = s.users.get(username);
  if (!user || !verifyPassword(password, user.hash)) {
    return NextResponse.json({ error: "bad credentials" }, { status: 401 });
  }

  return NextResponse.json({
    username: user.username,
    token: `session-${user.username}`,
  });
}
