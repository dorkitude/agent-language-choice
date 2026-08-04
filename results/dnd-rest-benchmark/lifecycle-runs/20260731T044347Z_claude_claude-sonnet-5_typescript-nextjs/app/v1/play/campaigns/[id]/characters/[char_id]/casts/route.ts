import { requireSession } from "../../../../../../auth/session.js";
import { parseJsonBody } from "../../../../../../http.js";
import { requirePlayCampaign } from "../../../../../http.js";
import { getTotalSpellSlots, isSpellcastingClass } from "../../../../../spells.js";
import {
  createPlayCast,
  getPlayMemberByCharacterId,
  hasPlayMemberForUser,
  listPlayCasts,
  listPlaySpells,
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
      { error: `only the owner of character ${characterId} may cast a spell` },
      { status: 403 },
    );
  }

  const parsed = await parseJsonBody(request);
  if (!parsed.ok) return parsed.response;
  const body = parsed.body as { spell_id?: unknown; target?: unknown };
  const { spell_id: spellId, target } = body ?? {};

  if (typeof spellId !== "string" || spellId.length === 0) {
    return Response.json({ error: "spell_id must be a non-empty string" }, { status: 400 });
  }
  if (typeof target !== "string" || target.length === 0) {
    return Response.json({ error: "target must be a non-empty string" }, { status: 400 });
  }

  if (!isSpellcastingClass(member.class)) {
    return Response.json(
      { error: `${member.class} is not a spellcasting class` },
      { status: 400 },
    );
  }

  const known = listPlaySpells(campaignId, characterId).find((spell) => spell.spell_id === spellId);
  const prepared = (member.prepared_spells ?? []).includes(spellId);
  if (!known || !prepared) {
    return Response.json(
      { error: `spell ${spellId} is not currently prepared for character ${characterId}` },
      { status: 400 },
    );
  }

  const spellLevel = known.level;
  const totalSlots = getTotalSpellSlots(member.class, member.level ?? 1, spellLevel);
  const existingCasts = listPlayCasts(campaignId, characterId);
  const usedSlots = existingCasts.filter((cast) => cast.slot_level === spellLevel).length;
  const slotsRemaining = totalSlots - usedSlots;

  if (slotsRemaining <= 0) {
    return Response.json(
      { error: `character ${characterId} has no remaining level ${spellLevel} spell slots` },
      { status: 409 },
    );
  }

  const cast = createPlayCast({
    campaign_id: campaignId,
    character_id: characterId,
    spell_id: spellId,
    target,
    slot_level: spellLevel,
    slots_remaining: slotsRemaining - 1,
    sequence: existingCasts.length + 1,
  });

  return Response.json(
    {
      character_id: characterId,
      spell_id: cast.spell_id,
      target: cast.target,
      slot_level: cast.slot_level,
      slots_remaining: cast.slots_remaining,
      sequence: cast.sequence,
    },
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

  const casts = listPlayCasts(campaignId, characterId).map((cast) => ({
    character_id: characterId,
    spell_id: cast.spell_id,
    target: cast.target,
    slot_level: cast.slot_level,
    slots_remaining: cast.slots_remaining,
    sequence: cast.sequence,
  }));

  return Response.json({ casts }, { status: 200 });
}
