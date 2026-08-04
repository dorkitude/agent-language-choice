import { NextResponse } from "next/server";
import { createSession, hasSession, sessionSummary, type InitiativeCombatant } from "../../../lib/combat";
import { badRequest, isInteger, isRecord, jsonBody } from "../../../lib/http";

export const runtime = "nodejs";

export async function POST(request: Request) {
  const body = await jsonBody(request);
  if (!isRecord(body) || typeof body.id !== "string" || body.id.length === 0 || !Array.isArray(body.combatants)) {
    return badRequest();
  }
  if (hasSession(body.id)) return badRequest("Session already exists");
  if (body.combatants.length === 0) return badRequest("At least one combatant is required");

  const names = new Set<string>();
  const order: InitiativeCombatant[] = [];
  for (const item of body.combatants) {
    if (!isRecord(item) || typeof item.name !== "string" || item.name.length === 0 || !isInteger(item.dex) || !isInteger(item.roll) || names.has(item.name)) {
      return badRequest("Invalid combatant");
    }
    names.add(item.name);
    order.push({ name: item.name, dex: item.dex, score: item.roll + item.dex });
  }
  order.sort((a, b) => b.score - a.score || b.dex - a.dex || a.name.localeCompare(b.name));
  return NextResponse.json(sessionSummary(createSession(body.id, order)));
}
