import { NextResponse } from "next/server";
import { abilityModifier } from "../../../lib/engine.js";
import { badRequest, parseJsonBody } from "../../../lib/http.js";

export async function POST(req: Request) {
  const parsed = await parseJsonBody(req);
  if (!parsed.ok) return parsed.response;

  const score = Number(parsed.body.score);

  if (!Number.isInteger(score) || score < 1 || score > 30) {
    return badRequest();
  }

  return NextResponse.json({ score, modifier: abilityModifier(score) });
}
