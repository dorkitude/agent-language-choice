import { requireBearerAuth } from "../../../../../../../lib/auth.js";
import {
  badRequest,
  conflict,
  created,
  forbidden,
  notFound,
  parseJsonBody,
} from "../../../../../../../lib/http.js";
import {
  createCombatAction,
  getEncounterTurn,
  getPlayCampaign,
  getPlayCampaignMembers,
} from "../../../../../../../lib/storage.js";
import { isNonEmptyString } from "../../../../../../../lib/validate.js";

export const dynamic = "force-dynamic";

const VALID_ACTION_TYPES = new Set(["attack", "help", "dodge", "ready"]);

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

  const members = getPlayCampaignMembers(id);
  const isMember = members.some((m) => m.username === auth.user.username);
  const isOwner = campaign.owner === auth.user.username;

  if (!isMember && !isOwner) {
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

  const b = parsed.body;
  if (
    !isNonEmptyString(b.type) ||
    !isNonEmptyString(b.target) ||
    !isNonEmptyString(b.text)
  ) {
    return badRequest();
  }

  if (!VALID_ACTION_TYPES.has(b.type)) {
    return badRequest();
  }

  const result = createCombatAction(
    id,
    auth.user.username,
    b.type,
    b.target,
    b.text
  );
  if (!result) {
    return conflict();
  }

  return created({
    sequence: result.sequence,
    kind: result.kind,
    actor: result.actor,
    type: result.type,
    target: result.target,
    text: result.text,
  });
}
