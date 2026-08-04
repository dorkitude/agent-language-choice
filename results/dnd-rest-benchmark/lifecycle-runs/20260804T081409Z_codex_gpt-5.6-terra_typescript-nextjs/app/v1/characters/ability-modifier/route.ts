import { NextResponse } from "next/server";
import { abilityModifier, isAbilityScore } from "../../../lib/characters";
import { badRequest, isRecord, jsonBody } from "../../../lib/http";

export async function POST(request: Request) {
  const body = await jsonBody(request);
  if (!isRecord(body) || !isAbilityScore(body.score)) return badRequest();

  return NextResponse.json({ score: body.score, modifier: abilityModifier(body.score) });
}
