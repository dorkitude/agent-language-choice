import { requireBearerAuth } from "../../../../../../../../lib/auth.js";
import {
  badRequest,
  created,
  forbidden,
  notFound,
  ok,
  parseJsonBody,
} from "../../../../../../../../lib/http.js";
import {
  addCharacterInventoryItem,
  getCharacterInventoryItems,
  getCharacterOwner,
  getPlayCampaign,
  getPlayCampaignMembers,
} from "../../../../../../../../lib/storage.js";

export const dynamic = "force-dynamic";

export async function GET(
  req: Request,
  { params }: { params: Promise<{ id: string; char_id: string }> }
) {
  const auth = requireBearerAuth(req);
  if (!auth.ok) return auth.response;

  const { id, char_id: character_id } = await params;

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

  const summary = getCharacterInventoryItems(id, character_id);
  if (!summary) {
    return notFound();
  }

  return ok(summary);
}

export async function POST(
  req: Request,
  { params }: { params: Promise<{ id: string; char_id: string }> }
) {
  const auth = requireBearerAuth(req);
  if (!auth.ok) return auth.response;

  const { id, char_id: character_id } = await params;

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
  if (
    typeof b.item_id !== "string" ||
    b.item_id.length === 0 ||
    !Number.isInteger(b.quantity) ||
    (b.quantity as number) < 1
  ) {
    return badRequest();
  }

  const result = addCharacterInventoryItem(
    id,
    character_id,
    b.item_id,
    b.quantity as number
  );

  if (result === "not_found") {
    return notFound();
  }
  if (result === "invalid") {
    return badRequest();
  }

  return created(result);
}
