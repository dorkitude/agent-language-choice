import { NextResponse } from "next/server";
import { isCharacterLevel, proficiencyBonus } from "../../../lib/characters";
import { badRequest, isRecord, jsonBody } from "../../../lib/http";

export async function POST(request: Request) {
  const body = await jsonBody(request);
  if (!isRecord(body) || !isCharacterLevel(body.level)) return badRequest();

  return NextResponse.json({ level: body.level, proficiency_bonus: proficiencyBonus(body.level) });
}
