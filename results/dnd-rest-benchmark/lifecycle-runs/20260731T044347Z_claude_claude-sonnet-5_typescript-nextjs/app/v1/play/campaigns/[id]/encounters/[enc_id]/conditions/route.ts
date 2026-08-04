import { requireSession } from "../../../../../../auth/session.js";
import { parseJsonBody, requireNonEmptyString } from "../../../../../../http.js";
import { requireCampaignOwner, requirePlayCampaign } from "../../../../../http.js";
import { encounterHasTarget, getPlayEncounter, updatePlayEncounter } from "../../../../../store.js";

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
    "only the owning dm may apply a condition",
  );
  if (ownerCheck) return ownerCheck;

  const encounter = getPlayEncounter(campaignId, encounterId);
  if (!encounter) {
    return Response.json({ error: `encounter ${encounterId} not found` }, { status: 404 });
  }

  const parsed = await parseJsonBody(request);
  if (!parsed.ok) return parsed.response;
  const body = parsed.body as { target?: unknown; condition?: unknown; duration_rounds?: unknown };

  const target = requireNonEmptyString(body.target, "target");
  if (target instanceof Response) return target;

  const condition = requireNonEmptyString(body.condition, "condition");
  if (condition instanceof Response) return condition;

  if (
    typeof body.duration_rounds !== "number" ||
    !Number.isInteger(body.duration_rounds) ||
    body.duration_rounds <= 0
  ) {
    return Response.json({ error: "duration_rounds must be a positive integer" }, { status: 400 });
  }
  const durationRounds = body.duration_rounds;

  if (!encounterHasTarget(encounter, target)) {
    return Response.json({ error: `target ${target} not found in encounter ${encounterId}` }, { status: 404 });
  }

  const conditions = encounter.conditions ?? {};
  const targetConditions = [...(conditions[target] ?? []), { condition, remaining_rounds: durationRounds }];

  updatePlayEncounter({
    ...encounter,
    conditions: { ...conditions, [target]: targetConditions },
  });

  return Response.json({ target, conditions: targetConditions }, { status: 201 });
}
