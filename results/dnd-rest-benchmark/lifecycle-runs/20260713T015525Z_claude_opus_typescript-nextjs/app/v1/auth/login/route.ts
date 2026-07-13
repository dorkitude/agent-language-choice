import { NextResponse } from "next/server";
import { getUser, verifyPassword } from "../store";

export async function POST(req: Request) {
  let body: unknown;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "invalid json" }, { status: 400 });
  }

  const obj =
    typeof body === "object" && body !== null
      ? (body as Record<string, unknown>)
      : {};
  const username = obj.username;
  const password = obj.password;

  if (typeof username !== "string" || typeof password !== "string") {
    return NextResponse.json({ error: "invalid credentials" }, { status: 400 });
  }

  const user = getUser(username);
  if (!user || !verifyPassword(password, user.hash)) {
    return NextResponse.json({ error: "bad credentials" }, { status: 401 });
  }

  return NextResponse.json({ username, token: `session-${username}` });
}
