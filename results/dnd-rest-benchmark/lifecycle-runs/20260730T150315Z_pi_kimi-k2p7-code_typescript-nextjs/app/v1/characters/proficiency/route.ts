import { NextResponse } from "next/server";
import { proficiencyBonus } from "../../../lib/engine.js";
import { badRequest, parseJsonBody } from "../../../lib/http.js";

export async function POST(req: Request) {
  const parsed = await parseJsonBody(req);
  if (!parsed.ok) return parsed.response;

  const level = Number(parsed.body.level);

  if (!Number.isInteger(level) || level < 1 || level > 20) {
    return badRequest();
  }

  return NextResponse.json({ level, proficiency_bonus: proficiencyBonus(level) });
}
