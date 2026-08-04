import { requireSession } from "../../../../../../auth/session.js";
import { parseJsonBody } from "../../../../../../http.js";
import { requireCampaignOwner, requirePlayCampaign } from "../../../../../http.js";
import { getPlayMemberByCharacterId, updatePlayMember } from "../../../../../store.js";

const DEFAULT_HP_MAX = 20;

export async function POST(
  request: Request,
  { params }: { params: Promise<{ id: string; char_id: string }> },
) {
  const { id: campaignId, char_id: characterId } = await params;

  const session = requireSession(request);
  if (!session.ok) return session.response;

  const campaign = requirePlayCampaign(campaignId);
  if (campaign instanceof Response) return campaign;

  const ownerCheck = requireCampaignOwner(
    campaign,
    session.user.username,
    "only the owning dm may apply damage",
  );
  if (ownerCheck) return ownerCheck;

  const member = getPlayMemberByCharacterId(campaignId, characterId);
  if (!member) {
    return Response.json(
      { error: `character ${characterId} not found in campaign ${campaignId}` },
      { status: 404 },
    );
  }

  const parsed = await parseJsonBody(request);
  if (!parsed.ok) return parsed.response;
  const body = parsed.body as { amount?: unknown };

  if (typeof body.amount !== "number" || !Number.isFinite(body.amount)) {
    return Response.json({ error: "amount must be a number" }, { status: 400 });
  }
  const amount = body.amount;

  const hpMax = member.hp_max ?? DEFAULT_HP_MAX;
  const hpBefore = member.hp_current ?? hpMax;
  const hpAfter = Math.max(0, hpBefore - amount);

  const becameUnconscious = hpAfter === 0 && member.status !== "dead" && member.status !== "stable";
  const status = becameUnconscious ? "unconscious" : (member.status ?? "conscious");

  const updated = {
    ...member,
    hp_current: hpAfter,
    hp_max: hpMax,
    status,
    death_save_successes: becameUnconscious ? 0 : member.death_save_successes,
    death_save_failures: becameUnconscious ? 0 : member.death_save_failures,
  };
  updatePlayMember(updated);

  return Response.json(
    {
      character_id: characterId,
      target: characterId,
      hp_before: hpBefore,
      hp_after: hpAfter,
      damage: amount,
      status,
    },
    { status: 200 },
  );
}
