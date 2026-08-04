import { NextResponse } from "next/server";
import { badRequest, conflict, notFound, parseJsonBody } from "../../../../../lib/http.js";
import { isNonEmptyString, isNonNegativeInteger, isPositiveInteger } from "../../../../../lib/validate.js";
import {
  createCraftingProject,
  getCampaign,
  getCampaignCharacters,
} from "../../../../../lib/storage.js";

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
    !isNonEmptyString(b.character_id) ||
    !isNonEmptyString(b.item_slug) ||
    !isPositiveInteger(b.days_required) ||
    !isNonNegativeInteger(b.cost_gp)
  ) {
    return badRequest();
  }

  const characters = getCampaignCharacters(id);
  if (!characters.some((c) => c.id === b.character_id)) {
    return notFound();
  }

  const result = createCraftingProject(id, {
    id: b.id,
    character_id: b.character_id,
    item_slug: b.item_slug,
    days_required: b.days_required,
    cost_gp: b.cost_gp,
  });
  if (!result) {
    return conflict();
  }

  return NextResponse.json(
    {
      id: result.id,
      character_id: result.character_id,
      item_slug: result.item_slug,
      days_required: result.days_required,
      days_completed: result.days_completed,
      status: result.status,
    },
    { status: 201 }
  );
}
