import { requireSession } from "../../../../../../auth/session.js";
import { parseJsonBody } from "../../../../../../http.js";
import { requirePlayCampaign } from "../../../../../http.js";
import { getPlayMemberByCharacterId, PlayMemberStatus, updatePlayMember } from "../../../../../store.js";

export async function POST(
  request: Request,
  { params }: { params: Promise<{ id: string; char_id: string }> },
) {
  const { id: campaignId, char_id: characterId } = await params;

  const session = requireSession(request);
  if (!session.ok) return session.response;

  const campaign = requirePlayCampaign(campaignId);
  if (campaign instanceof Response) return campaign;

  const member = getPlayMemberByCharacterId(campaignId, characterId);
  if (!member) {
    return Response.json(
      { error: `character ${characterId} not found in campaign ${campaignId}` },
      { status: 404 },
    );
  }

  if (session.user.username !== member.username) {
    return Response.json(
      { error: "only the character's owner may roll death saves" },
      { status: 403 },
    );
  }

  if (member.status !== "unconscious") {
    return Response.json(
      { error: `character ${characterId} is not unconscious` },
      { status: 409 },
    );
  }

  const parsed = await parseJsonBody(request);
  if (!parsed.ok) return parsed.response;
  const body = parsed.body as { outcome?: unknown };

  if (body.outcome !== "success" && body.outcome !== "failure") {
    return Response.json({ error: "outcome must be 'success' or 'failure'" }, { status: 400 });
  }

  let successes = member.death_save_successes ?? 0;
  let failures = member.death_save_failures ?? 0;

  if (body.outcome === "success") {
    successes += 1;
  } else {
    failures += 1;
  }

  let status: PlayMemberStatus = member.status;
  if (successes >= 3) {
    status = "stable";
  } else if (failures >= 3) {
    status = "dead";
  }

  updatePlayMember({
    ...member,
    death_save_successes: successes,
    death_save_failures: failures,
    status,
  });

  return Response.json(
    { character_id: characterId, successes, failures, status },
    { status: 201 },
  );
}
