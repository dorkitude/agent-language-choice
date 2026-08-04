import {
  getNextCampaignSession,
  listCampaignCharacters,
  listCampaignInventory,
  listCampaignNpcs,
  listCampaignQuests,
} from "../../../store.js";
import { requireCampaign } from "../../../http.js";
import { parseJsonBody } from "../../../../http.js";

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id: campaignId } = await params;

  const campaign = requireCampaign(campaignId);
  if (campaign instanceof Response) return campaign;

  const parsed = await parseJsonBody(request);
  if (!parsed.ok) return parsed.response;
  const body = parsed.body;

  const { include_zeroes } = (body ?? {}) as { include_zeroes?: unknown };

  if (include_zeroes !== undefined && typeof include_zeroes !== "boolean") {
    return Response.json({ error: "include_zeroes must be a boolean" }, { status: 400 });
  }

  const includeZeroes = include_zeroes === true;

  const characters = listCampaignCharacters(campaignId);
  const quests = listCampaignQuests(campaignId);
  const npcs = listCampaignNpcs(campaignId);
  const inventory = listCampaignInventory(campaignId);
  const nextSession = getNextCampaignSession(campaignId);

  const hasDm = typeof campaign?.dm === "string" && campaign.dm.length > 0;
  const hasCharacters = characters.length > 0;
  const hasNextSession = nextSession !== undefined;
  const hasActiveQuest = quests.some((quest) => quest.status === "active");

  const missing: string[] = [];
  if (!hasDm) missing.push("dm");
  if (!hasCharacters) missing.push("characters");
  if (!hasNextSession) missing.push("next_session");
  if (!hasActiveQuest) missing.push("active_quest");

  if (includeZeroes) {
    if (npcs.length === 0) missing.push("npcs");
    if (inventory.length === 0) missing.push("inventory");
  }

  const coreMissingCount = [hasDm, hasCharacters, hasNextSession, hasActiveQuest].filter(
    (signal) => !signal,
  ).length;

  let riskLevel: "low" | "medium" | "high";
  if (coreMissingCount === 0) {
    riskLevel = "low";
  } else if (coreMissingCount === 1) {
    riskLevel = "medium";
  } else {
    riskLevel = "high";
  }

  const report = {
    campaign_id: campaignId,
    risk_level: riskLevel,
    missing,
    signals: {
      has_dm: hasDm,
      has_characters: hasCharacters,
      has_next_session: hasNextSession,
      has_active_quest: hasActiveQuest,
    },
  };

  return Response.json(report);
}
