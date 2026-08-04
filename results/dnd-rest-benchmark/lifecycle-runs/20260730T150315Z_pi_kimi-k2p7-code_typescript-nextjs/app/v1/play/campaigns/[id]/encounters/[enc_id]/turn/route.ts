import { requireBearerAuth } from "../../../../../../../lib/auth.js";
import { forbidden, notFound, ok } from "../../../../../../../lib/http.js";
import {
  getEncounterTurn,
  getPlayCampaign,
  getPlayCampaignMembers,
} from "../../../../../../../lib/storage.js";

export const dynamic = "force-dynamic";

export async function GET(
  req: Request,
  { params }: { params: Promise<{ id: string; enc_id: string }> }
) {
  const auth = requireBearerAuth(req);
  if (!auth.ok) return auth.response;

  const { id, enc_id } = await params;

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

  const turn = getEncounterTurn(id, enc_id);
  if (!turn) {
    return notFound();
  }

  return ok({
    round: turn.round,
    turn_index: turn.turn_index,
    active: {
      name: turn.active.name,
      kind: turn.active.kind,
      initiative: turn.active.initiative,
    },
  });
}
