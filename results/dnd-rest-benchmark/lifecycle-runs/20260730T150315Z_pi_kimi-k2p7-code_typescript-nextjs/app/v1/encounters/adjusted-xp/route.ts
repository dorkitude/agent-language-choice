import { NextResponse } from "next/server";
import { adjustedXp } from "../../../lib/engine.js";
import { badRequest, parseJsonBody } from "../../../lib/http.js";

export async function POST(req: Request) {
  const parsed = await parseJsonBody(req);
  if (!parsed.ok) return parsed.response;

  const b = parsed.body;
  if (!Array.isArray(b.party) || !Array.isArray(b.monsters)) {
    return badRequest();
  }

  const result = adjustedXp(
    b.party as Array<{ level: number }>,
    b.monsters as Array<{ cr: string; count: number }>
  );

  if (!result) {
    return badRequest();
  }

  return NextResponse.json(result);
}
