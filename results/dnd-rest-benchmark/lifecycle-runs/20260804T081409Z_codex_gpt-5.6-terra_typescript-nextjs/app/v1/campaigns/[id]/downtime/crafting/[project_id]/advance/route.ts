import { NextResponse } from "next/server";
import { advanceCraftingProject, getCampaign } from "../../../../../../../lib/campaigns";
import { badRequest, isInteger, isRecord, jsonBody } from "../../../../../../../lib/http";

export const runtime = "nodejs";

export async function POST(request: Request, { params }: { params: Promise<{ id: string; project_id: string }> }) {
  const body = await jsonBody(request);
  if (!isRecord(body) || !isInteger(body.days) || body.days <= 0) return badRequest();

  const { id: campaignId, project_id: projectId } = await params;
  if (!getCampaign(campaignId)) return NextResponse.json({ error: "Unknown campaign" }, { status: 404 });
  const project = advanceCraftingProject(campaignId, projectId, body.days);
  if (!project) return NextResponse.json({ error: "Unknown crafting project" }, { status: 404 });
  return NextResponse.json(project);
}
