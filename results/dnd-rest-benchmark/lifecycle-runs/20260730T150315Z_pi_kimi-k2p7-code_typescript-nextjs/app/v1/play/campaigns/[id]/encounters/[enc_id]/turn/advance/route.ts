import { requireBearerAuth } from "../../../../../../../../lib/auth.js";
import {
  conflict,
  forbidden,
  notFound,
  ok,
} from "../../../../../../../../lib/http.js";
import {
  advanceEncounterTurn,
  getEncounterTurn,
  getPlayCampaign,
  getPlayCampaignMembers,
} from "../../../../../../../../lib/storage.js";

export const dynamic = "force-dynamic";

export async function POST(
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

  const isCurrentCombatant =
    turn.active.kind === "player" && turn.active.member === auth.user.username;

  if (!isOwner && !isCurrentCombatant) {
    return conflict();
  }

  const nextTurn = advanceEncounterTurn(id, enc_id);
  if (!nextTurn) {
    return conflict();
  }

  return ok({
    round: nextTurn.round,
    turn_index: nextTurn.turn_index,
    active: {
      name: nextTurn.active.name,
      kind: nextTurn.active.kind,
      initiative: nextTurn.active.initiative,
    },
  });
}
