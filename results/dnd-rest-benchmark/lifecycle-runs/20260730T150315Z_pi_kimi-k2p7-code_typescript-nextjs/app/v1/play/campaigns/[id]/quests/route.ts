import { requireBearerAuth } from "../../../../../lib/auth.js";
import {
  badRequest,
  conflict,
  created,
  forbidden,
  notFound,
  ok,
  parseJsonBody,
} from "../../../../../lib/http.js";
import {
  createPlayCampaignQuest,
  getPlayCampaign,
  getPlayCampaignMembers,
  getPlayCampaignQuests,
} from "../../../../../lib/storage.js";
import { isNonEmptyString } from "../../../../../lib/validate.js";

export const dynamic = "force-dynamic";

export async function POST(
  req: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const auth = requireBearerAuth(req, "dm");
  if (!auth.ok) return auth.response;

  const { id } = await params;
  const campaign = getPlayCampaign(id);
  if (!campaign) {
    return notFound();
  }

  if (campaign.owner !== auth.user.username) {
    return forbidden();
  }

  const parsed = await parseJsonBody(req);
  if (!parsed.ok) return parsed.response;

  const b = parsed.body;
  if (!isNonEmptyString(b.quest_id) || !isNonEmptyString(b.title)) {
    return badRequest();
  }

  if (!Array.isArray(b.depends_on)) {
    return badRequest();
  }
  if (!b.depends_on.every((item: unknown) => typeof item === "string")) {
    return badRequest();
  }
  const dependsOn = b.depends_on as string[];
  if (new Set(dependsOn).size !== dependsOn.length) {
    return badRequest();
  }
  if (dependsOn.includes(b.quest_id)) {
    return badRequest();
  }

  const result = createPlayCampaignQuest(id, {
    quest_id: b.quest_id,
    title: b.title,
    depends_on: dependsOn,
  });

  if (result === "bad_request") {
    return badRequest();
  }
  if (result === "conflict") {
    return conflict();
  }

  return created(result);
}

export async function GET(
  req: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const auth = requireBearerAuth(req);
  if (!auth.ok) return auth.response;

  const { id } = await params;
  const campaign = getPlayCampaign(id);
  if (!campaign) {
    return notFound();
  }

  const members = getPlayCampaignMembers(id);
  const isOwner = campaign.owner === auth.user.username;
  const member = members.find((m) => m.username === auth.user.username);

  if (!isOwner && !member) {
    return forbidden();
  }

  return ok({ quests: getPlayCampaignQuests(id) });
}
