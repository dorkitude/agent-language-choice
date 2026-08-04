import { NextResponse } from "next/server";
import { badRequest, conflict, notFound, parseJsonBody } from "../../../../lib/http.js";
import { isNonEmptyString, isPositiveInteger } from "../../../../lib/validate.js";
import { addCampaignInventoryItem, getCampaign } from "../../../../lib/storage.js";

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
    !isNonEmptyString(b.item_slug) ||
    !isNonEmptyString(b.owner) ||
    !isPositiveInteger(b.quantity)
  ) {
    return badRequest();
  }

  const result = addCampaignInventoryItem(id, {
    item_slug: b.item_slug,
    quantity: b.quantity,
    owner: b.owner,
  });
  if (!result) {
    return conflict();
  }

  return NextResponse.json(result, { status: 201 });
}
