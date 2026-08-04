import { requireBearerAuth } from "../../../../../../../../lib/auth.js";
import {
  badRequest,
  conflict,
  forbidden,
  notFound,
  ok,
  parseJsonBody,
} from "../../../../../../../../lib/http.js";
import {
  delayEncounterTurn,
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

  const parsed = await parseJsonBody(req);
  if (!parsed.ok) return parsed.response;

  const b = parsed.body;
  let rawIndex: unknown = b.new_index;
  if (rawIndex === undefined) rawIndex = b.index;
  if (rawIndex === undefined) rawIndex = b.to_index;

  if (typeof rawIndex !== "number" || !Number.isInteger(rawIndex)) {
    return badRequest();
  }

  const result = delayEncounterTurn(id, enc_id, rawIndex);
  if (result === null) {
    return notFound();
  }
  if (result === "invalid_index") {
    return badRequest();
  }

  return ok({
    order: result.order.map((c) => ({
      name: c.name,
      kind: c.kind,
      initiative: c.initiative,
    })),
  });
}
