import { NextResponse } from "next/server";
import { initiativeOrder } from "../../../lib/engine.js";
import { badRequest, parseJsonBody } from "../../../lib/http.js";

export async function POST(req: Request) {
  const parsed = await parseJsonBody(req);
  if (!parsed.ok) return parsed.response;

  const combatants = parsed.body.combatants;
  if (!Array.isArray(combatants)) {
    return badRequest();
  }

  return NextResponse.json({
    order: initiativeOrder(combatants as Array<{
      name: string;
      dex: number;
      roll: number;
    }>),
  });
}
