import { NextResponse } from "next/server";
import { badRequest, conflict, notFound, parseJsonBody } from "../../../../lib/http.js";
import { isInteger, isNonEmptyString } from "../../../../lib/validate.js";
import { createNpc, getCampaign, getFaction } from "../../../../lib/storage.js";

export const dynamic = "force-dynamic";

export async function POST(
  req: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;

  if (!getCampaign(id)) {
    return notFound();
  }

  const parsed = await parseJsonBody(req);
  if (!parsed.ok) return parsed.response;

  const b = parsed.body;
  if (
    !isNonEmptyString(b.id) ||
    typeof b.name !== "string" ||
    !isNonEmptyString(b.faction_id) ||
    !isInteger(b.disposition)
  ) {
    return badRequest();
  }

  if (!getFaction(id, b.faction_id)) {
    return badRequest();
  }

  const result = createNpc(id, {
    id: b.id,
    name: b.name,
    faction_id: b.faction_id,
    disposition: b.disposition,
  });
  if (!result) {
    return conflict();
  }

  return NextResponse.json(result, { status: 201 });
}
