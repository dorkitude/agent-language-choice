import { requireSession } from "../../../../../../auth/session.js";
import { parseJsonBody, requireNonEmptyString } from "../../../../../../http.js";
import { requireCampaignOwner, requirePlayCampaign } from "../../../../../http.js";
import { getPlayEncounter, updatePlayEncounter } from "../../../../../store.js";

export async function POST(
  request: Request,
  { params }: { params: Promise<{ id: string; enc_id: string }> },
) {
  const { id: campaignId, enc_id: encounterId } = await params;

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

  const encounter = getPlayEncounter(campaignId, encounterId);
  if (!encounter) {
    return Response.json({ error: `encounter ${encounterId} not found` }, { status: 404 });
  }

  const parsed = await parseJsonBody(request);
  if (!parsed.ok) return parsed.response;
  const body = parsed.body as { target?: unknown; amount?: unknown };

  const target = requireNonEmptyString(body.target, "target");
  if (target instanceof Response) return target;

  if (typeof body.amount !== "number" || !Number.isFinite(body.amount)) {
    return Response.json({ error: "amount must be a number" }, { status: 400 });
  }
  const amount = body.amount;

  const monsters = encounter.monsters ?? [];
  const monster = monsters.find((candidate) => candidate.monster_id === target);
  if (!monster) {
    return Response.json({ error: `target ${target} not found in encounter ${encounterId}` }, { status: 404 });
  }

  const hpBefore = monster.hp_current;
  const hpAfter = Math.max(0, hpBefore - amount);

  updatePlayEncounter({
    ...encounter,
    monsters: monsters.map((candidate) =>
      candidate.monster_id === target ? { ...candidate, hp_current: hpAfter } : candidate,
    ),
  });

  return Response.json(
    { target, hp_before: hpBefore, hp_after: hpAfter, damage: amount },
    { status: 200 },
  );
}
