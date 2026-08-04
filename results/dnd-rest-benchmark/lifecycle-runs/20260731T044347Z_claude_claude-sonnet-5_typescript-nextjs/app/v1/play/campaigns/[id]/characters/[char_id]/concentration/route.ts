import { requireSession } from "../../../../../../auth/session.js";
import { parseJsonBody } from "../../../../../../http.js";
import { requirePlayCampaign } from "../../../../../http.js";
import { isSpellcastingClass } from "../../../../../spells.js";
import {
  getPlayMemberByCharacterId,
  hasPlayMemberForUser,
  listPlaySpells,
  updatePlayMember,
} from "../../../../../store.js";

export async function PUT(
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
      { error: `only the owner of character ${characterId} may set concentration` },
      { status: 403 },
    );
  }

  const parsed = await parseJsonBody(request);
  if (!parsed.ok) return parsed.response;
  const body = parsed.body as {
    spell_id?: unknown;
    target?: unknown;
    duration_turns?: unknown;
  };
  const { spell_id: spellId, target, duration_turns: durationTurns } = body ?? {};

  if (typeof spellId !== "string" || spellId.length === 0) {
    return Response.json({ error: "spell_id must be a non-empty string" }, { status: 400 });
  }
  if (typeof target !== "string" || target.length === 0) {
    return Response.json({ error: "target must be a non-empty string" }, { status: 400 });
  }
  if (typeof durationTurns !== "number" || !Number.isInteger(durationTurns) || durationTurns < 1) {
    return Response.json({ error: "duration_turns must be a positive integer" }, { status: 400 });
  }

  if (!isSpellcastingClass(member.class)) {
    return Response.json(
      { error: `${member.class} is not a spellcasting class` },
      { status: 400 },
    );
  }

  const known = listPlaySpells(campaignId, characterId).some((spell) => spell.spell_id === spellId);
  const prepared = (member.prepared_spells ?? []).includes(spellId);
  if (!known || !prepared) {
    return Response.json(
      { error: `spell ${spellId} is not currently prepared for character ${characterId}` },
      { status: 400 },
    );
  }

  const concentration = {
    spell_id: spellId,
    target,
    remaining_turns: durationTurns,
  };

  updatePlayMember({ ...member, concentration });

  return Response.json(
    { character_id: characterId, concentration },
    { status: 200 },
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

  return Response.json(
    { character_id: characterId, concentration: member.concentration ?? null },
    { status: 200 },
  );
}

export async function DELETE(
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
      { error: `only the owner of character ${characterId} may clear concentration` },
      { status: 403 },
    );
  }

  updatePlayMember({ ...member, concentration: null });

  return Response.json(
    { character_id: characterId, concentration: null },
    { status: 200 },
  );
}
