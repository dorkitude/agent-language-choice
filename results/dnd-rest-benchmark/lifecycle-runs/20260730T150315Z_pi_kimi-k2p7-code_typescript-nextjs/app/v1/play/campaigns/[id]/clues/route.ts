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
  createPlayCampaignClue,
  getPlayCampaign,
  getPlayCampaignClues,
  getPlayCampaignMembers,
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
  const audience = b.audience;
  if (
    !isNonEmptyString(b.clue_id) ||
    !isNonEmptyString(b.text) ||
    !isNonEmptyString(audience) ||
    (audience !== "character" && audience !== "party" && audience !== "hidden")
  ) {
    return badRequest();
  }

  const typedAudience = audience as "character" | "party" | "hidden";

  if (typedAudience === "character") {
    if (!isNonEmptyString(b.character_id)) {
      return badRequest();
    }
    const members = getPlayCampaignMembers(id);
    if (!members.some((m) => m.character_id === b.character_id)) {
      return badRequest();
    }
  } else if (b.character_id !== undefined) {
    return badRequest();
  }

  const result = createPlayCampaignClue(id, {
    clue_id: b.clue_id,
    text: b.text,
    audience: typedAudience,
    character_id: typedAudience === "character" ? b.character_id : undefined,
  });

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

  const clues = getPlayCampaignClues(id);
  let visibleClues = clues;
  if (!isOwner) {
    const myCharacterId = member?.character_id;
    visibleClues = clues.filter((c) => {
      if (c.audience === "party") return true;
      if (c.audience === "character" && c.character_id === myCharacterId) {
        return true;
      }
      return false;
    });
  }

  return ok({ clues: visibleClues });
}
