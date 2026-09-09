import { NextResponse } from "next/server";
import {
  forbidden,
  notFound,
  unauthorized,
} from "../../../../../lib/http.js";
import {
  getPlayCampaign,
  getPlayCampaignMembers,
  getPlayCampaignSpectator,
  rebuildPlayCampaignProjection,
} from "../../../../../lib/storage.js";

export const dynamic = "force-dynamic";

function parseSpectatorToken(req: Request):
  | { ok: true; spectator_id: string }
  | { ok: false; response: ReturnType<typeof unauthorized> | ReturnType<typeof forbidden> } {
  const header = req.headers.get("Authorization");
  if (!header || !header.startsWith("Bearer ")) {
    return { ok: false, response: unauthorized() };
  }

  const token = header.slice("Bearer ".length);
  if (token.startsWith("session-")) {
    return { ok: false, response: forbidden() };
  }

  if (!token.startsWith("spectator-")) {
    return { ok: false, response: unauthorized() };
  }

  const spectatorId = token.slice("spectator-".length);
  if (spectatorId.length === 0) {
    return { ok: false, response: unauthorized() };
  }

  return { ok: true, spectator_id: spectatorId };
}

export async function GET(
  req: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const auth = parseSpectatorToken(req);
  if (!auth.ok) return auth.response;

  const { id } = await params;
  const spectator = getPlayCampaignSpectator(auth.spectator_id);
  if (!spectator) {
    return unauthorized();
  }

  if (spectator.campaign_id !== id) {
    // A valid spectator ticket for a different existing campaign is 403;
    // if the target campaign does not exist, the spec requires 404.
    if (getPlayCampaign(id)) {
      return forbidden();
    }
    return notFound();
  }

  const campaign = getPlayCampaign(id);
  if (!campaign) {
    return notFound();
  }

  const projection = rebuildPlayCampaignProjection(id);
  const partySize = getPlayCampaignMembers(id).length;

  return NextResponse.json({
    campaign_id: id,
    name: campaign.name,
    status: campaign.status,
    party_size: partySize,
    story: projection?.story ?? "",
  });
}
