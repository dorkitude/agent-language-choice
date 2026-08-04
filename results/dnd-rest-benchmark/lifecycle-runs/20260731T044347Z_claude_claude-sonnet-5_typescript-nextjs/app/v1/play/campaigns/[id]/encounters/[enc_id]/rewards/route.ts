import { requireSession } from "../../../../../../auth/session.js";
import { parseJsonBody, requireNonEmptyString } from "../../../../../../http.js";
import { requireCampaignOwner, requirePlayCampaign } from "../../../../../http.js";
import {
  PlayEncounterLootItem,
  getPlayEncounter,
  updatePlayEncounter,
} from "../../../../../store.js";

function parseLoot(value: unknown): PlayEncounterLootItem[] | Response {
  if (!Array.isArray(value)) {
    return Response.json({ error: "loot must be an array" }, { status: 400 });
  }
  const loot: PlayEncounterLootItem[] = [];
  for (const entry of value) {
    const item = entry as { slug?: unknown; quantity?: unknown };
    const validSlug = requireNonEmptyString(item.slug, "loot[].slug");
    if (validSlug instanceof Response) return validSlug;
    if (typeof item.quantity !== "number" || !Number.isInteger(item.quantity) || item.quantity <= 0) {
      return Response.json({ error: "loot[].quantity must be a positive integer" }, { status: 400 });
    }
    loot.push({ slug: validSlug, quantity: item.quantity });
  }
  return loot;
}

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
    "only the owning dm may award encounter rewards",
  );
  if (ownerCheck) return ownerCheck;

  const encounter = getPlayEncounter(campaignId, encounterId);
  if (!encounter) {
    return Response.json({ error: `encounter ${encounterId} not found` }, { status: 404 });
  }

  if (encounter.rewards) {
    return Response.json(
      { error: `rewards already awarded for encounter ${encounterId}` },
      { status: 409 },
    );
  }

  const parsed = await parseJsonBody(request);
  if (!parsed.ok) return parsed.response;
  const body = parsed.body as { xp?: unknown; loot?: unknown };

  if (typeof body.xp !== "number" || !Number.isInteger(body.xp) || body.xp < 0) {
    return Response.json({ error: "xp must be a non-negative integer" }, { status: 400 });
  }
  const xp = body.xp;

  const loot = parseLoot(body.loot ?? []);
  if (loot instanceof Response) return loot;

  const rewards = { xp, loot };

  updatePlayEncounter({ ...encounter, rewards });

  return Response.json({ id: encounter.id, xp, loot }, { status: 200 });
}
