import { NextResponse } from "next/server";
import {
  authStore,
  hashPassword,
  validPassword,
  validRole,
  validUsername,
  type User,
} from "../../../lib/auth";

export async function POST(req: Request) {
  let body: unknown;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "invalid JSON" }, { status: 400 });
  }

  const obj =
    body && typeof body === "object" ? (body as Record<string, unknown>) : {};
  const { username, password, role } = obj;

  if (!validUsername(username)) {
    return NextResponse.json({ error: "invalid username" }, { status: 400 });
  }
  if (!validPassword(password)) {
    return NextResponse.json({ error: "invalid password" }, { status: 400 });
  }
  if (!validRole(role)) {
    return NextResponse.json({ error: "invalid role" }, { status: 400 });
  }

  const s = authStore();
  if (s.users.has(username)) {
    return NextResponse.json({ error: "duplicate username" }, { status: 409 });
  }

  const user: User = { username, role, hash: hashPassword(password) };
  s.users.set(username, user);

  return NextResponse.json({ username: user.username, role: user.role });
}
