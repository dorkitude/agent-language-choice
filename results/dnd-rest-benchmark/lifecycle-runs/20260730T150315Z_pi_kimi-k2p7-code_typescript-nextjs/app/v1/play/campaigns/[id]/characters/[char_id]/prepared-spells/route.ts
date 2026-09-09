import { requireBearerAuth } from "../../../../../../../lib/auth.js";
import {
  isSpellcastingClass,
  maxPreparedSpells,
} from "../../../../../../../lib/engine.js";
import {
  badRequest,
  forbidden,
  notFound,
  ok,
  parseJsonBody,
} from "../../../../../../../lib/http.js";
import {
  getCharacterClassAndLevel,
  getCharacterKnownSpellIds,
  getCharacterOwner,
  getCharacterPreparedSpells,
  getPlayCampaign,
  getPlayCampaignMembers,
  setCharacterPreparedSpells,
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

  const classAndLevel = getCharacterClassAndLevel(id, char_id);
  if (!classAndLevel) {
    return notFound();
  }

  const preparedSpells = getCharacterPreparedSpells(id, char_id) ?? [];

  return ok({
    character_id: char_id,
    prepared_spells: preparedSpells,
    max_prepared: maxPreparedSpells(classAndLevel.class, classAndLevel.level),
  });
}

export async function PUT(
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
  if (!Array.isArray(b.spell_ids)) {
    return badRequest();
  }
  const spellIds = b.spell_ids as unknown[];
  if (!spellIds.every((id) => typeof id === "string")) {
    return badRequest();
  }

  const classAndLevel = getCharacterClassAndLevel(id, char_id);
  if (!classAndLevel) {
    return notFound();
  }

  if (!isSpellcastingClass(classAndLevel.class)) {
    return badRequest();
  }

  const knownSpells = getCharacterKnownSpellIds(id, char_id);
  if (!knownSpells) {
    return notFound();
  }

  for (const spellId of spellIds) {
    if (!knownSpells.has(spellId as string)) {
      return badRequest();
    }
  }

  const maxPrepared = maxPreparedSpells(
    classAndLevel.class,
    classAndLevel.level
  );
  if (spellIds.length > maxPrepared) {
    return badRequest();
  }

  const stored = setCharacterPreparedSpells(
    id,
    char_id,
    spellIds as string[]
  );
  if (!stored) {
    return notFound();
  }

  return ok({
    character_id: char_id,
    prepared_spells: spellIds as string[],
    max_prepared: maxPrepared,
  });
}
