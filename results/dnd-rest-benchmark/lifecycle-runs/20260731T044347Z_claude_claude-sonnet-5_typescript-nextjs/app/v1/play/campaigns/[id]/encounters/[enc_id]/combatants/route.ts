import { requireSession } from "../../../../../../auth/session.js";
import { parseJsonBody, requireNonEmptyString } from "../../../../../../http.js";
import { requireCampaignOwner, requirePlayCampaign } from "../../../../../http.js";
import { getPlayEncounter, getPlayMemberForUser, updatePlayEncounter } from "../../../../../store.js";

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
    "only the owning dm may bind a combatant",
  );
  if (ownerCheck) return ownerCheck;

  const encounter = getPlayEncounter(campaignId, encounterId);
  if (!encounter) {
    return Response.json({ error: `encounter ${encounterId} not found` }, { status: 404 });
  }

  const parsed = await parseJsonBody(request);
  if (!parsed.ok) return parsed.response;
  const body = parsed.body as { member?: unknown; initiative?: unknown };

  const memberUsername = requireNonEmptyString(body.member, "member");
  if (memberUsername instanceof Response) return memberUsername;

  if (typeof body.initiative !== "number" || !Number.isFinite(body.initiative)) {
    return Response.json({ error: "initiative must be a number" }, { status: 400 });
  }
  const initiative = body.initiative;

  const member = getPlayMemberForUser(campaignId, memberUsername);
  if (!member) {
    return Response.json({ error: `member ${memberUsername} not found` }, { status: 400 });
  }

  const combatants = encounter.combatants ?? [];
  if (combatants.some((combatant) => combatant.member === memberUsername)) {
    return Response.json(
      { error: `member ${memberUsername} is already bound to encounter ${encounterId}` },
      { status: 409 },
    );
  }

  const combatant = {
    member: memberUsername,
    character_id: member.character_id,
    name: member.name,
    initiative,
  };

  updatePlayEncounter({ ...encounter, combatants: [...combatants, combatant] });

  return Response.json(combatant, { status: 201 });
}
