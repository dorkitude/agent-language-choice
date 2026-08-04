import { NextResponse } from "next/server";
import { loginUser } from "../../../lib/auth.js";
import { badRequest, parseJsonBody, unauthorized } from "../../../lib/http.js";

export const dynamic = "force-dynamic";

export async function POST(req: Request) {
  const parsed = await parseJsonBody(req);
  if (!parsed.ok) return parsed.response;

  const b = parsed.body;
  if (typeof b.username !== "string" || typeof b.password !== "string") {
    return badRequest();
  }

  const result = await loginUser(b.username, b.password);
  if (!result) {
    return unauthorized();
  }

  return NextResponse.json(result);
}
