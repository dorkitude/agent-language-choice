import { NextResponse } from "next/server";
import { requireBearerAuth } from "../../../../../lib/auth.js";
import { badRequest, conflict, forbidden, notFound, parseJsonBody } from "../../../../../lib/http.js";
import {
  getPlayCampaign,
  getPlayCampaignMember,
  getPlayCampaignSessionZero,
  getPlayCampaignState,
  setPlayCampaignSessionZero,
} from "../../../../../lib/storage.js";

export const dynamic = "force-dynamic";

export async function PUT(
  req: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const auth = requireBearerAuth(req, "dm");
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
  if (
    typeof b.rules !== "string" ||
    b.rules.length === 0 ||
    typeof b.tone !== "string" ||
    b.tone.length === 0
  ) {
    return badRequest();
  }

  if (!Array.isArray(b.consent) || b.consent.length === 0) {
    return badRequest();
  }

  const consent: string[] = [];
  const seen = new Set<string>();
  for (const item of b.consent) {
    if (typeof item !== "string" || item.length === 0 || seen.has(item)) {
      return badRequest();
    }
    seen.add(item);
    consent.push(item);
  }

  if (getPlayCampaignState(id)) {
    return conflict();
  }

  const settings = { rules: b.rules, tone: b.tone, consent };
  const result = setPlayCampaignSessionZero(id, settings);
  if (!result) {
    return conflict();
  }

  return NextResponse.json(result);
}

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

  const isMember =
    campaign.owner === auth.user.username ||
    getPlayCampaignMember(id, auth.user.username) !== null;
  if (!isMember) {
    return forbidden();
  }

  const settings = getPlayCampaignSessionZero(id);
  if (!settings) {
    return notFound();
  }

  return NextResponse.json(settings);
}
