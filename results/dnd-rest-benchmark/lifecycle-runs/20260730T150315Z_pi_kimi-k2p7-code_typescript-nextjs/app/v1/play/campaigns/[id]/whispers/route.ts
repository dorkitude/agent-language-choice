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
  createWhisper,
  getPlayCampaign,
  getPlayCampaignMember,
  getPlayCampaignMembers,
  getWhispers,
  type CreateWhisperInput,
} from "../../../../../lib/storage.js";

export const dynamic = "force-dynamic";

function isValidWhisperPayload(
  body: Record<string, unknown>
): CreateWhisperInput | null {
  if (
    typeof body.whisper_id !== "string" ||
    body.whisper_id.length === 0 ||
    typeof body.to_character_id !== "string" ||
    body.to_character_id.length === 0 ||
    typeof body.text !== "string" ||
    body.text.length === 0
  ) {
    return null;
  }

  return {
    whisper_id: body.whisper_id,
    to_character_id: body.to_character_id,
    text: body.text,
  };
}

export async function POST(
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

  if (campaign.owner === auth.user.username) {
    return forbidden();
  }

  const membership = getPlayCampaignMember(id, auth.user.username);
  if (!membership) {
    return forbidden();
  }

  const parsed = await parseJsonBody(req);
  if (!parsed.ok) return parsed.response;

  const payload = isValidWhisperPayload(parsed.body);
  if (!payload) {
    return badRequest();
  }

  const members = getPlayCampaignMembers(id);
  const targetExists = members.some(
    (m) => m.character_id === payload.to_character_id
  );
  if (!targetExists) {
    return badRequest();
  }

  const result = createWhisper(id, membership.character_id, payload);
  if (!result) {
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

  const isMember =
    campaign.owner === auth.user.username ||
    getPlayCampaignMember(id, auth.user.username) !== null;
  if (!isMember) {
    return forbidden();
  }

  const isDm = campaign.owner === auth.user.username;
  const whispers = getWhispers(id);

  let visibleWhispers;
  if (isDm) {
    visibleWhispers = whispers;
  } else {
    const membership = getPlayCampaignMember(id, auth.user.username);
    const ownedCharacterId = membership?.character_id;
    visibleWhispers = whispers.filter(
      (w) =>
        w.from_character_id === ownedCharacterId ||
        w.to_character_id === ownedCharacterId
    );
  }

  return ok({ whispers: visibleWhispers });
}
