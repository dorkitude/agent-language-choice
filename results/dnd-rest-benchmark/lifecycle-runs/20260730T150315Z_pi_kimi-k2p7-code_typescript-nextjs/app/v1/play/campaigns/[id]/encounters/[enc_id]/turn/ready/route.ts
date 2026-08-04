import { requireBearerAuth } from "../../../../../../../../lib/auth.js";
import {
  badRequest,
  conflict,
  created,
  forbidden,
  notFound,
  parseJsonBody,
} from "../../../../../../../../lib/http.js";
import {
  createReadyAction,
  getEncounterTurn,
  getPlayCampaign,
  getPlayCampaignMembers,
} from "../../../../../../../../lib/storage.js";
import { isNonEmptyString } from "../../../../../../../../lib/validate.js";

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

  if (!isCurrentCombatant) {
    return conflict();
  }

  const parsed = await parseJsonBody(req);
  if (!parsed.ok) return parsed.response;

  const trigger = parsed.body.trigger;
  if (!isNonEmptyString(trigger)) {
    return badRequest();
  }

  const result = createReadyAction(id, enc_id, auth.user.username, trigger);
  if (!result) {
    return notFound();
  }

  return created(result);
}
