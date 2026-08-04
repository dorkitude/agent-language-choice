import { NextResponse } from "next/server";
import { abilityCheck } from "../../../lib/engine.js";
import { badRequest, parseJsonBody } from "../../../lib/http.js";

export async function POST(req: Request) {
  const parsed = await parseJsonBody(req);
  if (!parsed.ok) return parsed.response;

  const b = parsed.body;
  const roll = Number(b.roll);
  const modifier = Number(b.modifier);
  const dc = Number(b.dc);

  if (
    !Number.isInteger(roll) ||
    !Number.isInteger(modifier) ||
    !Number.isInteger(dc)
  ) {
    return badRequest();
  }

  return NextResponse.json(abilityCheck(roll, modifier, dc));
}
