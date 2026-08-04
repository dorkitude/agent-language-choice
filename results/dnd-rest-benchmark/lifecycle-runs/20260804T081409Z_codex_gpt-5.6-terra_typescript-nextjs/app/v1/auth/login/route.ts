import { NextResponse } from "next/server";
import { authenticateUser } from "../../../lib/users";
import { badRequest, isRecord, jsonBody } from "../../../lib/http";

export const runtime = "nodejs";

export async function POST(request: Request) {
  const body = await jsonBody(request);
  if (!isRecord(body) || typeof body.username !== "string" || typeof body.password !== "string") {
    return badRequest();
  }

  if (!authenticateUser(body.username, body.password)) {
    return NextResponse.json({ error: "Invalid credentials" }, { status: 401 });
  }

  return NextResponse.json({ username: body.username, token: `session-${body.username}` });
}
