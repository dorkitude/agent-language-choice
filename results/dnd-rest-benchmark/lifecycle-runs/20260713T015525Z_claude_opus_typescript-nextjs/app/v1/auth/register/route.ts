import { NextResponse } from "next/server";
import { hasUser, createUser, hashPassword, USERNAME_RE } from "../store";

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
  const role = obj.role;

  if (typeof username !== "string" || !USERNAME_RE.test(username)) {
    return NextResponse.json({ error: "invalid username" }, { status: 400 });
  }
  if (typeof password !== "string" || password.length < 8) {
    return NextResponse.json({ error: "invalid password" }, { status: 400 });
  }
  if (role !== "dm" && role !== "player") {
    return NextResponse.json({ error: "invalid role" }, { status: 400 });
  }

  if (hasUser(username)) {
    return NextResponse.json({ error: "duplicate username" }, { status: 409 });
  }

  createUser({ username, role, hash: hashPassword(password) });

  return NextResponse.json({ username, role }, { status: 201 });
}
