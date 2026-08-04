import { NextResponse } from "next/server";
import { badRequest, conflict, notFound, parseJsonBody } from "../../../../lib/http.js";
import { createCampaignEvent, getCampaign } from "../../../../lib/storage.js";

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
    typeof b.kind !== "string" ||
    typeof b.summary !== "string"
  ) {
    return badRequest();
  }

  const result = createCampaignEvent(id, {
    id: b.id,
    kind: b.kind,
    summary: b.summary,
  });
  if (!result) {
    return conflict();
  }

  return NextResponse.json(
    { id: result.id, kind: result.kind },
    { status: 201 }
  );
}
