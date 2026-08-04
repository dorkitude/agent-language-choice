import { requireSession } from "../../../../../../auth/session.js";
import { parseJsonBody, requireNonEmptyString } from "../../../../../../http.js";
import { requireCampaignOwner, requirePlayCampaign } from "../../../../../http.js";
import {
  createPlayFactionReputationEntry,
  getPlayFaction,
  getPlayFactionReputationTotal,
  getPlayMemberForUser,
  hasPlayMemberCharacter,
  listPlayFactionReputationEntries,
  MAX_FACTION_REPUTATION,
  MIN_FACTION_REPUTATION,
  setPlayFactionReputationTotal,
} from "../../../../../store.js";
import type { PlayFactionReputationEntry } from "../../../../../store.js";

export async function POST(
  request: Request,
  { params }: { params: Promise<{ id: string; faction_id: string }> },
) {
  const { id: campaignId, faction_id: factionId } = await params;

  const session = requireSession(request);
  if (!session.ok) return session.response;

  const campaign = requirePlayCampaign(campaignId);
  if (campaign instanceof Response) return campaign;

  const ownerCheck = requireCampaignOwner(
    campaign,
    session.user.username,
    "only the campaign dm may change faction reputation",
  );
  if (ownerCheck) return ownerCheck;

  const faction = getPlayFaction(campaignId, factionId);
  if (!faction) {
    return Response.json({ error: `faction ${factionId} not found` }, { status: 404 });
  }

  const parsed = await parseJsonBody(request);
  if (!parsed.ok) return parsed.response;
  const body = parsed.body as { character_id?: unknown; delta?: unknown; reason?: unknown };

  const validCharacterId = requireNonEmptyString(body.character_id, "character_id");
  if (validCharacterId instanceof Response) return validCharacterId;

  if (!hasPlayMemberCharacter(campaignId, validCharacterId)) {
    return Response.json(
      { error: `character ${validCharacterId} is not a member of campaign ${campaignId}` },
      { status: 400 },
    );
  }

  const { delta } = body;
  if (
    typeof delta !== "number" ||
    !Number.isInteger(delta) ||
    delta === 0 ||
    delta < -25 ||
    delta > 25
  ) {
    return Response.json(
      { error: "delta must be a nonzero integer between -25 and 25" },
      { status: 400 },
    );
  }

  const validReason = requireNonEmptyString(body.reason, "reason");
  if (validReason instanceof Response) return validReason;

  const currentTotal = getPlayFactionReputationTotal(campaignId, factionId, validCharacterId);
  const newTotal = Math.max(
    MIN_FACTION_REPUTATION,
    Math.min(MAX_FACTION_REPUTATION, currentTotal + delta),
  );
  setPlayFactionReputationTotal(campaignId, factionId, validCharacterId, newTotal);

  const entry = createPlayFactionReputationEntry(campaignId, {
    faction_id: factionId,
    character_id: validCharacterId,
    reputation: newTotal,
    delta,
    reason: validReason,
  });

  return Response.json(
    {
      faction_id: entry.faction_id,
      character_id: entry.character_id,
      reputation: entry.reputation,
      delta: entry.delta,
      reason: entry.reason,
    },
    { status: 201 },
  );
}

export async function GET(
  request: Request,
  { params }: { params: Promise<{ id: string; faction_id: string }> },
) {
  const { id: campaignId, faction_id: factionId } = await params;

  const session = requireSession(request);
  if (!session.ok) return session.response;

  const campaign = requirePlayCampaign(campaignId);
  if (campaign instanceof Response) return campaign;

  const username = session.user.username;
  const member = getPlayMemberForUser(campaignId, username);
  const isOwner = username === campaign.owner;
  if (!isOwner && !member) {
    return Response.json({ error: `${username} is not a member of campaign ${campaignId}` }, { status: 403 });
  }

  const faction = getPlayFaction(campaignId, factionId);
  if (!faction) {
    return Response.json({ error: `faction ${factionId} not found` }, { status: 404 });
  }

  const allEntries = listPlayFactionReputationEntries(campaignId, factionId);
  const entries = isOwner
    ? allEntries
    : allEntries.filter((entry: PlayFactionReputationEntry) => entry.character_id === member?.character_id);

  return Response.json(
    {
      faction_id: factionId,
      entries: entries.map((entry: PlayFactionReputationEntry) => ({
        faction_id: entry.faction_id,
        character_id: entry.character_id,
        reputation: entry.reputation,
        delta: entry.delta,
        reason: entry.reason,
      })),
    },
    { status: 200 },
  );
}
