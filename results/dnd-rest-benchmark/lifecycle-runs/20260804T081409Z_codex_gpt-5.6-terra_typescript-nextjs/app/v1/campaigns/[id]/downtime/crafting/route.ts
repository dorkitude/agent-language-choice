import { NextResponse } from "next/server";
import { createCraftingProject, getCampaign, hasCampaignCharacter } from "../../../../../lib/campaigns";
import { badRequest, isInteger, isNonEmptyString, isRecord, jsonBody } from "../../../../../lib/http";

export const runtime = "nodejs";

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const body = await jsonBody(request);
  if (!isRecord(body) || !isNonEmptyString(body.id) || !isNonEmptyString(body.character_id) ||
    !isNonEmptyString(body.item_slug) || !isInteger(body.days_required) || body.days_required <= 0 ||
    typeof body.cost_gp !== "number" || !Number.isFinite(body.cost_gp) || body.cost_gp < 0) {
    return badRequest();
  }

  const campaignId = (await params).id;
  if (!getCampaign(campaignId)) return NextResponse.json({ error: "Unknown campaign" }, { status: 404 });
  if (!hasCampaignCharacter(campaignId, body.character_id)) {
    return NextResponse.json({ error: "Unknown character" }, { status: 404 });
  }
  const project = createCraftingProject(campaignId, {
    id: body.id,
    character_id: body.character_id,
    item_slug: body.item_slug,
    days_required: body.days_required,
    cost_gp: body.cost_gp,
  });
  if (!project) return NextResponse.json({ error: "Crafting project already exists" }, { status: 409 });
  return NextResponse.json(project, { status: 201 });
}
