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
  addCharacterSpell,
  getCharacterClass,
  getCharacterOwner,
  getCharacterSpells,
  getPlayCampaign,
  getPlayCampaignMembers,
  type SpellbookSpell,
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

  const spells = getCharacterSpells(id, char_id);
  if (spells === null) {
    return notFound();
  }

  return ok({ spells });
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
    typeof b.name !== "string" ||
    b.name.length === 0 ||
    !Number.isInteger(b.level) ||
    (b.level as number) < 0 ||
    (b.level as number) > 9
  ) {
    return badRequest();
  }

  const spell: SpellbookSpell = {
    spell_id: b.spell_id,
    name: b.name,
    level: b.level as number,
  };

  const characterClass = getCharacterClass(id, char_id);
  if (!characterClass) {
    return notFound();
  }

  if (characterClass.toLowerCase() !== "wizard") {
    return badRequest();
  }

  const result = addCharacterSpell(id, char_id, spell);
  if (result === "not_found") {
    return notFound();
  }
  if (result === "conflict") {
    return conflict();
  }

  return created(result);
}
