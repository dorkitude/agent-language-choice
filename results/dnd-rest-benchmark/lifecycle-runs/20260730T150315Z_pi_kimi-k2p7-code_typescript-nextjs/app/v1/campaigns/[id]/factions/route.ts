import { NextResponse } from "next/server";
import { badRequest, conflict, notFound, parseJsonBody } from "../../../../lib/http.js";
import { isNonEmptyString } from "../../../../lib/validate.js";
import { createFaction, getCampaign } from "../../../../lib/storage.js";

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
    typeof b.stance !== "string"
  ) {
    return badRequest();
  }

  const result = createFaction(id, {
    id: b.id,
    name: b.name,
    stance: b.stance,
  });
  if (!result) {
    return conflict();
  }

  return NextResponse.json(result, { status: 201 });
}
