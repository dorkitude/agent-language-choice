import { requireBearerAuth } from "../../../../../../../lib/auth.js";
import {
  badRequest,
  conflict,
  created,
  forbidden,
  notFound,
  ok,
  parseJsonBody,
} from "../../../../../../../lib/http.js";
import {
  getCharacterSpellCasts,
  getCharacterOwner,
  getPlayCampaign,
  getPlayCampaignMembers,
  recordCharacterSpellCast,
} from "../../../../../../../lib/storage.js";

export const dynamic = "force-dynamic";

export async function GET(
  req: Request,
  { params }: { params: Promise<{ id: string; char_id: string }> }
) {
  const auth = requireBearerAuth(req);
  if (!auth.ok) return auth.response;

  const { id, char_id } = await params;

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

  const casts = getCharacterSpellCasts(id, char_id);
  if (casts === null) {
    return notFound();
  }

  return ok({ casts });
}

export async function POST(
  req: Request,
  { params }: { params: Promise<{ id: string; char_id: string }> }
) {
  const auth = requireBearerAuth(req);
  if (!auth.ok) return auth.response;

  const { id, char_id } = await params;

  const campaign = getPlayCampaign(id);
  if (!campaign) {
    return notFound();
  }

  const ownerRecord = getCharacterOwner(id, char_id);
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
    typeof b.spell_id !== "string" ||
    b.spell_id.length === 0 ||
    typeof b.target !== "string" ||
    b.target.length === 0
  ) {
    return badRequest();
  }

  const result = recordCharacterSpellCast(
    id,
    char_id,
    b.spell_id,
    b.target
  );

  if (result === "not_found") {
    return notFound();
  }
  if (result === "not_spellcaster" || result === "not_known" || result === "not_prepared") {
    return badRequest();
  }
  if (result === "no_slots") {
    return conflict();
  }

  return created(result);
}
