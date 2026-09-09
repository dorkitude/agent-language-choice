import { NextResponse } from "next/server";
import { requireBearerAuth } from "../../../../../lib/auth.js";
import { badRequest, conflict, forbidden, notFound, parseJsonBody } from "../../../../../lib/http.js";
import {
  getPlayCampaign,
  getPlayCampaignMember,
  grantDelegation,
} from "../../../../../lib/storage.js";

export const dynamic = "force-dynamic";

function isValidDelegationPayload(
  body: Record<string, unknown>
): { username: string; powers: string[] } | null {
  if (typeof body.username !== "string") {
    return null;
  }

  if (!Array.isArray(body.powers) || body.powers.length === 0) {
    return null;
  }

  const powers: string[] = [];
  const seen = new Set<string>();
  for (const p of body.powers) {
    if (typeof p !== "string") {
      return null;
    }
    if (p !== "narrate") {
      return null;
    }
    if (seen.has(p)) {
      return null;
    }
    seen.add(p);
    powers.push(p);
  }

  return { username: body.username, powers };
}

export async function POST(
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

  const payload = isValidDelegationPayload(parsed.body);
  if (!payload) {
    return badRequest();
  }

  const member = getPlayCampaignMember(id, payload.username);
  if (!member) {
    return badRequest();
  }

  const result = grantDelegation(id, payload.username, payload.powers);
  if (result === null) {
    return notFound();
  }
  if (result === "conflict") {
    return conflict();
  }

  return NextResponse.json(result, { status: 201 });
}
