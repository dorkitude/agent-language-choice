import { NextResponse } from "next/server";
import { badRequest, isInteger, isRecord, jsonBody } from "../../../lib/http";

type Combatant = { name: string; dex: number; roll: number; score: number };

export async function POST(request: Request) {
  const body = await jsonBody(request);
  if (!isRecord(body) || !Array.isArray(body.combatants)) return badRequest();

  const combatants: Combatant[] = [];
  for (const item of body.combatants) {
    if (!isRecord(item) || typeof item.name !== "string" || !isInteger(item.dex) || !isInteger(item.roll)) {
      return badRequest("Invalid combatant");
    }
    combatants.push({ name: item.name, dex: item.dex, roll: item.roll, score: item.roll + item.dex });
  }
  combatants.sort((a, b) => b.score - a.score || b.dex - a.dex || a.name.localeCompare(b.name));
  return NextResponse.json({ order: combatants.map(({ name, score }) => ({ name, score })) });
}
