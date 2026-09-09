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
  createPlayCampaignNpcDialogue,
  getPlayCampaign,
  getPlayCampaignMembers,
  getPlayCampaignNpc,
  getPlayCampaignNpcDialogue,
} from "../../../../../../../lib/storage.js";

export const dynamic = "force-dynamic";

export async function POST(
  req: Request,
  { params }: { params: Promise<{ id: string; npc_id: string }> }
) {
  const auth = requireBearerAuth(req, "dm");
  if (!auth.ok) return auth.response;

  const { id, npc_id } = await params;

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
  if (
    typeof b.dialogue_id !== "string" ||
    b.dialogue_id.length === 0 ||
    typeof b.speaker !== "string" ||
    b.speaker.length === 0 ||
    typeof b.text !== "string" ||
    b.text.length === 0 ||
    (b.visibility !== "public" && b.visibility !== "private")
  ) {
    return badRequest();
  }

  const npc = getPlayCampaignNpc(id, npc_id);
  if (!npc) {
    return notFound();
  }

  const result = createPlayCampaignNpcDialogue(id, npc_id, {
    dialogue_id: b.dialogue_id,
    speaker: b.speaker,
    text: b.text,
    visibility: b.visibility,
  });

  if (!result) {
    return conflict();
  }

  return created({
    dialogue_id: result.dialogue_id,
    speaker: result.speaker,
    text: result.text,
    visibility: result.visibility,
  });
}

export async function GET(
  req: Request,
  { params }: { params: Promise<{ id: string; npc_id: string }> }
) {
  const auth = requireBearerAuth(req);
  if (!auth.ok) return auth.response;

  const { id, npc_id } = await params;

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

  const npc = getPlayCampaignNpc(id, npc_id);
  if (!npc) {
    return notFound();
  }

  const entries = getPlayCampaignNpcDialogue(id, npc_id);
  const visibleEntries = isOwner
    ? entries
    : entries.filter((e) => e.visibility === "public");

  return ok({
    npc_id: npc_id,
    entries: visibleEntries,
  });
}
