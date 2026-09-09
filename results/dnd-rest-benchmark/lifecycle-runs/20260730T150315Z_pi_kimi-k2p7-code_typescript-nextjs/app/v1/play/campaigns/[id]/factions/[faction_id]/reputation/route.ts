import { requireBearerAuth } from "../../../../../../../lib/auth.js";
import {
  badRequest,
  created,
  forbidden,
  notFound,
  ok,
  parseJsonBody,
} from "../../../../../../../lib/http.js";
import {
  createPlayCampaignReputation,
  getPlayCampaign,
  getPlayCampaignFaction,
  getPlayCampaignMembers,
  getPlayCampaignReputationHistory,
} from "../../../../../../../lib/storage.js";

export const dynamic = "force-dynamic";

export async function POST(
  req: Request,
  { params }: { params: Promise<{ id: string; faction_id: string }> }
) {
  const auth = requireBearerAuth(req, "dm");
  if (!auth.ok) return auth.response;

  const { id, faction_id } = await params;

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
    typeof b.character_id !== "string" ||
    b.character_id.length === 0 ||
    typeof b.reason !== "string" ||
    b.reason.length === 0 ||
    typeof b.delta !== "number" ||
    !Number.isInteger(b.delta) ||
    b.delta === 0 ||
    Math.abs(b.delta) > 25
  ) {
    return badRequest();
  }

  const faction = getPlayCampaignFaction(id, faction_id);
  if (!faction) {
    return notFound();
  }

  const members = getPlayCampaignMembers(id);
  const isMemberCharacter = members.some(
    (m) => m.character_id === b.character_id
  );
  if (!isMemberCharacter) {
    return badRequest();
  }

  const result = createPlayCampaignReputation(id, faction_id, {
    character_id: b.character_id,
    delta: b.delta,
    reason: b.reason,
  });

  if (!result) {
    return badRequest();
  }

  return created({
    faction_id: result.faction_id,
    character_id: result.character_id,
    reputation: result.reputation,
    delta: result.delta,
    reason: result.reason,
  });
}

export async function GET(
  req: Request,
  { params }: { params: Promise<{ id: string; faction_id: string }> }
) {
  const auth = requireBearerAuth(req);
  if (!auth.ok) return auth.response;

  const { id, faction_id } = await params;

  const campaign = getPlayCampaign(id);
  if (!campaign) {
    return notFound();
  }

  const members = getPlayCampaignMembers(id);
  const isMember = members.some((m) => m.username === auth.user.username);
  const isOwner = campaign.owner === auth.user.username;

  if (!isMember && !isOwner) {
    return forbidden();
  }

  const faction = getPlayCampaignFaction(id, faction_id);
  if (!faction) {
    return notFound();
  }

  let entries;
  if (isOwner) {
    entries = getPlayCampaignReputationHistory(id, faction_id);
  } else {
    const characterIds = members
      .filter((m) => m.username === auth.user.username)
      .map((m) => m.character_id);
    entries = characterIds.flatMap((characterId) =>
      getPlayCampaignReputationHistory(id, faction_id, characterId)
    );
  }

  return ok({
    faction_id: faction_id,
    entries,
  });
}
