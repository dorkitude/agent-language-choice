import { requireBearerAuth } from "../../../../../../../lib/auth.js";
import {
  created,
  forbidden,
  notFound,
  ok,
} from "../../../../../../../lib/http.js";
import {
  discoverSettlement,
  getPlayCampaign,
  getPlayCampaignMembers,
  getSettlement,
} from "../../../../../../../lib/storage.js";
import type { Settlement } from "../../../../../../../lib/types.js";

export const dynamic = "force-dynamic";

function toPlayerSettlement(
  settlement: Settlement,
  characterId: string
): Settlement {
  return {
    ...settlement,
    discovered_by: settlement.discovered_by.includes(characterId)
      ? [characterId]
      : [],
  };
}

export async function POST(
  req: Request,
  { params }: { params: Promise<{ id: string; settlement_id: string }> }
) {
  const auth = requireBearerAuth(req, "player");
  if (!auth.ok) return auth.response;

  const { id, settlement_id } = await params;

  const campaign = getPlayCampaign(id);
  if (!campaign) {
    return notFound();
  }

  if (campaign.owner === auth.user.username) {
    return forbidden();
  }

  const members = getPlayCampaignMembers(id);
  const playerMembership = members.find((m) => m.username === auth.user.username);
  if (!playerMembership) {
    return forbidden();
  }

  const characterId = playerMembership.character_id;

  const existingSettlement = getSettlement(id, settlement_id);
  if (!existingSettlement) {
    return notFound();
  }

  const wasAlreadyDiscovered = existingSettlement.discovered_by.includes(
    characterId
  );

  const result = discoverSettlement(id, settlement_id, characterId);

  if (result === "not_found") {
    return notFound();
  }
  if (result === "not_member") {
    return notFound();
  }

  const playerView = toPlayerSettlement(result, characterId);

  if (wasAlreadyDiscovered) {
    return ok(playerView);
  }

  return created(playerView);
}
