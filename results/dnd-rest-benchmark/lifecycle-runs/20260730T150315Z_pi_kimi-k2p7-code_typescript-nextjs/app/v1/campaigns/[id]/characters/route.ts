import { NextResponse } from "next/server";
import { badRequest, conflict, notFound, parseJsonBody } from "../../../../lib/http.js";
import { isInteger } from "../../../../lib/validate.js";
import { createCampaignCharacter, getCampaign } from "../../../../lib/storage.js";

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
    typeof b.id !== "string" ||
    typeof b.name !== "string" ||
    typeof b.class !== "string" ||
    !isInteger(b.level)
  ) {
    return badRequest();
  }

  const result = createCampaignCharacter(id, {
    id: b.id,
    name: b.name,
    level: b.level,
    class: b.class,
  });
  if (!result) {
    return conflict();
  }

  return NextResponse.json(result, { status: 201 });
}
