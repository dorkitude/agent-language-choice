import { NextResponse } from "next/server";
import { badRequest, notFound, parseJsonBody } from "../../../../../../lib/http.js";
import { isNonEmptyString, isPositiveInteger } from "../../../../../../lib/validate.js";
import { assignEquipment, getCampaign } from "../../../../../../lib/storage.js";

export const dynamic = "force-dynamic";

export async function POST(
  req: Request,
  { params }: { params: Promise<{ id: string; character_id: string }> }
) {
  const { id, character_id } = await params;

  if (!getCampaign(id)) {
    return notFound();
  }

  const parsed = await parseJsonBody(req);
  if (!parsed.ok) return parsed.response;

  const b = parsed.body;
  if (!isNonEmptyString(b.item_slug) || !isPositiveInteger(b.quantity)) {
    return badRequest();
  }

  const result = assignEquipment(id, character_id, {
    item_slug: b.item_slug,
    quantity: b.quantity,
  });
  if (!result) {
    return notFound();
  }

  return NextResponse.json(result, { status: 200 });
}
