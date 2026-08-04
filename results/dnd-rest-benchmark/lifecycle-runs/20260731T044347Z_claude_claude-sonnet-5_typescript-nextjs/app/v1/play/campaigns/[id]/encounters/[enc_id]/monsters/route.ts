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
    "only the owning dm may add a monster",
  );
  if (ownerCheck) return ownerCheck;

  const encounter = getPlayEncounter(campaignId, encounterId);
  if (!encounter) {
    return Response.json({ error: `encounter ${encounterId} not found` }, { status: 404 });
  }

  const parsed = await parseJsonBody(request);
  if (!parsed.ok) return parsed.response;
  const body = parsed.body as {
    monster_id?: unknown;
    name?: unknown;
    hp_max?: unknown;
    initiative?: unknown;
  };

  const monsterId = requireNonEmptyString(body.monster_id, "monster_id");
  if (monsterId instanceof Response) return monsterId;

  const name = requireNonEmptyString(body.name, "name");
  if (name instanceof Response) return name;

  if (typeof body.hp_max !== "number" || !Number.isFinite(body.hp_max)) {
    return Response.json({ error: "hp_max must be a number" }, { status: 400 });
  }
  const hpMax = body.hp_max;

  if (typeof body.initiative !== "number" || !Number.isFinite(body.initiative)) {
    return Response.json({ error: "initiative must be a number" }, { status: 400 });
  }
  const initiative = body.initiative;

  const monsters = encounter.monsters ?? [];
  if (monsters.some((monster) => monster.monster_id === monsterId)) {
    return Response.json(
      { error: `monster ${monsterId} already exists` },
      { status: 409 },
    );
  }

  const monster = {
    monster_id: monsterId,
    name,
    hp_max: hpMax,
    initiative,
    hp_current: hpMax,
  };

  updatePlayEncounter({ ...encounter, monsters: [...monsters, monster] });

  return Response.json(monster, { status: 201 });
}
