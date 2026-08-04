import { requireSession } from "../../../../../../auth/session.js";
import { parseJsonBody } from "../../../../../../http.js";
import { requirePlayCampaign } from "../../../../../http.js";
import { findClassSpell } from "../../../../../spells.js";
import {
  createPlaySpell,
  getPlayMemberByCharacterId,
  hasPlayMemberForUser,
  hasPlaySpell,
  listPlaySpells,
  PlaySpell,
} from "../../../../../store.js";

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

  const username = session.user.username;
  const currentOwner = member.owner ?? member.username;
  if (currentOwner !== username) {
    return Response.json(
      { error: `only the owner of character ${characterId} may add a spell` },
      { status: 403 },
    );
  }

  const parsed = await parseJsonBody(request);
  if (!parsed.ok) return parsed.response;
  const body = parsed.body as { spell_id?: unknown; name?: unknown; level?: unknown };
  const { spell_id: spellId, name, level } = body ?? {};

  if (typeof spellId !== "string" || spellId.length === 0) {
    return Response.json({ error: "spell_id must be a non-empty string" }, { status: 400 });
  }
  if (typeof name !== "string" || name.length === 0) {
    return Response.json({ error: "name must be a non-empty string" }, { status: 400 });
  }
  if (typeof level !== "number" || !Number.isInteger(level) || level < 0) {
    return Response.json({ error: "level must be a non-negative integer" }, { status: 400 });
  }

  const definition = findClassSpell(spellId, name, level, member.class);
  if (!definition) {
    return Response.json(
      { error: `${spellId} is not a valid spell for class ${member.class}` },
      { status: 400 },
    );
  }

  if (hasPlaySpell(campaignId, characterId, spellId)) {
    return Response.json(
      { error: `character ${characterId} already knows spell ${spellId}` },
      { status: 409 },
    );
  }

  createPlaySpell({
    campaign_id: campaignId,
    character_id: characterId,
    spell_id: definition.spell_id,
    name: definition.name,
    level: definition.level,
  });

  return Response.json(
    { spell_id: definition.spell_id, name: definition.name, level: definition.level },
    { status: 201 },
  );
}

export async function GET(
  request: Request,
  { params }: { params: Promise<{ id: string; char_id: string }> },
) {
  const { id: campaignId, char_id: characterId } = await params;

  const session = requireSession(request);
  if (!session.ok) return session.response;

  const campaign = requirePlayCampaign(campaignId);
  if (campaign instanceof Response) return campaign;

  const username = session.user.username;
  const isMember = username === campaign.owner || hasPlayMemberForUser(campaignId, username);
  if (!isMember) {
    return Response.json(
      { error: `${username} is not a member of campaign ${campaignId}` },
      { status: 403 },
    );
  }

  const member = getPlayMemberByCharacterId(campaignId, characterId);
  if (!member) {
    return Response.json(
      { error: `character ${characterId} not found in campaign ${campaignId}` },
      { status: 404 },
    );
  }

  const spells = listPlaySpells(campaignId, characterId).map((spell: PlaySpell) => ({
    spell_id: spell.spell_id,
    name: spell.name,
    level: spell.level,
  }));

  return Response.json({ spells }, { status: 200 });
}
