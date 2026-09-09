import { requireBearerAuth } from "../../../../../../../../lib/auth.js";
import {
  badRequest,
  forbidden,
  notFound,
  ok,
  parseJsonBody,
} from "../../../../../../../../lib/http.js";
import {
  equipCharacterItem,
  getCharacterEquipment,
  getCharacterOwner,
  getPlayCampaign,
  getPlayCampaignMembers,
} from "../../../../../../../../lib/storage.js";

export const dynamic = "force-dynamic";

export async function GET(
  req: Request,
  { params }: { params: Promise<{ id: string; char_id: string; slot: string }> }
) {
  const auth = requireBearerAuth(req);
  if (!auth.ok) return auth.response;

  const { id, char_id: character_id, slot } = await params;

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

  const result = getCharacterEquipment(id, character_id, slot);

  if (result === "not_found") {
    return notFound();
  }
  if (result === "invalid") {
    return badRequest();
  }

  return ok(result);
}

export async function PUT(
  req: Request,
  { params }: { params: Promise<{ id: string; char_id: string; slot: string }> }
) {
  const auth = requireBearerAuth(req);
  if (!auth.ok) return auth.response;

  const { id, char_id: character_id, slot } = await params;

  const campaign = getPlayCampaign(id);
  if (!campaign) {
    return notFound();
  }

  const ownerRecord = getCharacterOwner(id, character_id);
  if (!ownerRecord) {
    return notFound();
  }

  if (!ownerRecord.owner || ownerRecord.owner !== auth.user.username) {
    return forbidden();
  }

  const parsed = await parseJsonBody(req);
  if (!parsed.ok) return parsed.response;

  const b = parsed.body;
  if (typeof b.item_id !== "string" || b.item_id.length === 0) {
    return badRequest();
  }

  const result = equipCharacterItem(id, character_id, slot, b.item_id);

  if (result === "not_found") {
    return notFound();
  }
  if (result === "invalid") {
    return badRequest();
  }

  return ok(result);
}
