import { requireSession } from "../../../../../auth/session.js";
import { parseJsonBody } from "../../../../../http.js";
import { requirePlayCampaign } from "../../../../http.js";
import {
  createPlayEvent,
  getNextPlayEventSequence,
  getPlayMemberForUser,
  updatePlayCampaign,
  updatePlayMember,
} from "../../../../store.js";

const DEFAULT_HP_MAX = 20;

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id: campaignId } = await params;

  const session = requireSession(request);
  if (!session.ok) return session.response;

  const campaign = requirePlayCampaign(campaignId);
  if (campaign instanceof Response) return campaign;

  const username = session.user.username;
  const currentActor = campaign.current_actor ?? null;

  // Only the player currently up in the queue may rest; the owner never
  // acts through this endpoint. Mirrors the check in POST /actions.
  if (username === campaign.owner || currentActor === null || username !== currentActor) {
    return Response.json({ error: "it is not your turn to act" }, { status: 409 });
  }

  const parsed = await parseJsonBody(request);
  if (!parsed.ok) return parsed.response;
  const body = parsed.body;

  const { type } = (body ?? {}) as { type?: unknown };

  if (type !== "short" && type !== "long") {
    return Response.json({ error: "type must be 'short' or 'long'" }, { status: 400 });
  }

  const member = getPlayMemberForUser(campaignId, username);
  if (!member) {
    return Response.json({ error: `${username} has no membership in campaign ${campaignId}` }, { status: 409 });
  }

  const hpMax = member.hp_max ?? DEFAULT_HP_MAX;
  const hpCurrent = type === "long" ? hpMax : (member.hp_current ?? hpMax);

  updatePlayMember({
    ...member,
    hp_current: hpCurrent,
    hp_max: hpMax,
  });

  const sequence = getNextPlayEventSequence(campaignId);
  const event = createPlayEvent(campaignId, {
    sequence,
    kind: "rest",
    actor: username,
    type,
    text: `Took a ${type} rest`,
  });

  updatePlayCampaign({
    ...campaign,
    current_actor: campaign.owner,
  });

  return Response.json(
    {
      sequence: event.sequence,
      kind: event.kind,
      actor: event.actor,
      type,
      hp_current: hpCurrent,
      hp_max: hpMax,
      next_actor: "dm",
    },
    { status: 201 },
  );
}
