import { NextResponse } from "next/server";
import { createUser } from "../../../lib/users";
import { badRequest, isRecord, jsonBody } from "../../../lib/http";

export const runtime = "nodejs";

const USERNAME = /^[a-z0-9_-]{2,32}$/;

export async function POST(request: Request) {
  const body = await jsonBody(request);
  if (
    !isRecord(body) ||
    typeof body.username !== "string" ||
    !USERNAME.test(body.username) ||
    typeof body.password !== "string" ||
    body.password.length < 8 ||
    (body.role !== "dm" && body.role !== "player")
  ) {
    return badRequest();
  }

  if (!createUser(body.username, body.password, body.role)) {
    return NextResponse.json({ error: "Username already exists" }, { status: 409 });
  }

  return NextResponse.json({ username: body.username, role: body.role }, { status: 201 });
}
