import { NextResponse } from "next/server";
import { advanceTurn } from "../../../../../lib/engine.js";
import { getCombatSession, replaceCombatSession } from "../../../../../lib/storage.js";
import { notFound } from "../../../../../lib/http.js";

export const dynamic = "force-dynamic";

export async function POST(
  _req: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;

  const session = getCombatSession(id);
  if (!session) {
    return notFound();
  }

  const result = advanceTurn(session);
  replaceCombatSession(session);

  return NextResponse.json(result);
}
