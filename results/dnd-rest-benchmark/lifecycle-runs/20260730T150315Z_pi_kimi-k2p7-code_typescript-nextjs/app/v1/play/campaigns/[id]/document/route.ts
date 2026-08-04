import { NextResponse } from "next/server";
import { requireBearerAuth } from "../../../../../lib/auth.js";
import { badRequest, conflict, forbidden, notFound, parseJsonBody } from "../../../../../lib/http.js";
import {
  getCampaignDocument,
  getPlayCampaign,
  getPlayCampaignMembers,
  updateCampaignDocument,
} from "../../../../../lib/storage.js";

export const dynamic = "force-dynamic";

export async function GET(
  req: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const auth = requireBearerAuth(req);
  if (!auth.ok) return auth.response;

  const { id } = await params;

  const campaign = getPlayCampaign(id);
  if (!campaign) {
    return notFound();
  }

  const isOwner = campaign.owner === auth.user.username;
  const members = getPlayCampaignMembers(id);
  const isMember = members.some((m) => m.username === auth.user.username);

  if (!isOwner && !isMember) {
    return forbidden();
  }

  const document = getCampaignDocument(id) ?? {
    campaign_id: id,
    story: "",
    dm_notes: "",
  };

  if (isOwner) {
    return NextResponse.json({
      story: document.story,
      dm_notes: document.dm_notes,
    });
  }

  return NextResponse.json({
    story: document.story,
  });
}

export async function PUT(
  req: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const auth = requireBearerAuth(req);
  if (!auth.ok) return auth.response;

  const { id } = await params;

  const campaign = getPlayCampaign(id);
  if (!campaign) {
    return notFound();
  }

  if (campaign.owner !== auth.user.username) {
    return forbidden();
  }

  const parsed = await parseJsonBody(req);
  if (!parsed.ok) return parsed.response;

  const b = parsed.body;
  if (typeof b.story !== "string" || typeof b.dm_notes !== "string") {
    return badRequest();
  }

  const result = updateCampaignDocument(id, b.story, b.dm_notes);
  if (!result) {
    return conflict();
  }

  return NextResponse.json({
    story: result.story,
    dm_notes: result.dm_notes,
  });
}
