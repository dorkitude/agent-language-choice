import { requireSession } from "../../../../../../auth/session.js";
import { parseJsonBody } from "../../../../../../http.js";
import { requirePlayCampaign } from "../../../../../http.js";
import { maxPreparedSpells } from "../../../../../spells.js";
import {
  getPlayMemberByCharacterId,
  hasPlayMemberForUser,
  hasPlaySpell,
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
      { error: `only the owner of character ${characterId} may prepare spells` },
      { status: 403 },
    );
  }

  const parsed = await parseJsonBody(request);
  if (!parsed.ok) return parsed.response;
  const body = parsed.body as { spell_ids?: unknown };
  const { spell_ids: spellIds } = body ?? {};

  if (!Array.isArray(spellIds) || !spellIds.every((spellId) => typeof spellId === "string")) {
    return Response.json({ error: "spell_ids must be an array of strings" }, { status: 400 });
  }

  const maxPrepared = maxPreparedSpells(member.class, member.level ?? 1);
  if (maxPrepared === 0) {
    return Response.json(
      { error: `${member.class} is not a spellcasting class` },
      { status: 400 },
    );
  }

  for (const spellId of spellIds) {
    if (!hasPlaySpell(campaignId, characterId, spellId)) {
      return Response.json(
        { error: `character ${characterId} does not know spell ${spellId}` },
        { status: 400 },
      );
    }
  }

  if (spellIds.length > maxPrepared) {
    return Response.json(
      { error: `character ${characterId} may prepare at most ${maxPrepared} spells` },
      { status: 400 },
    );
  }

  updatePlayMember({ ...member, prepared_spells: spellIds });

  return Response.json(
    { character_id: characterId, prepared_spells: spellIds, max_prepared: maxPrepared },
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

  const maxPrepared = maxPreparedSpells(member.class, member.level ?? 1);

  return Response.json(
    {
      character_id: characterId,
      prepared_spells: member.prepared_spells ?? [],
      max_prepared: maxPrepared,
    },
    { status: 200 },
  );
}
