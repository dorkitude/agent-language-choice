import { NextResponse } from "next/server";
import {
  isValidPassword,
  isValidRole,
  isValidUsername,
  registerUser,
} from "../../../lib/auth.js";
import { badRequest, conflict, parseJsonBody } from "../../../lib/http.js";

export const dynamic = "force-dynamic";

export async function POST(req: Request) {
  const parsed = await parseJsonBody(req);
  if (!parsed.ok) return parsed.response;

  const b = parsed.body;
  if (
    !isValidUsername(b.username) ||
    !isValidPassword(b.password) ||
    !isValidRole(b.role)
  ) {
    return badRequest();
  }

  const result = await registerUser(b.username, b.password, b.role);
  if (!result) {
    return conflict();
  }

  return NextResponse.json(result, { status: 201 });
}
