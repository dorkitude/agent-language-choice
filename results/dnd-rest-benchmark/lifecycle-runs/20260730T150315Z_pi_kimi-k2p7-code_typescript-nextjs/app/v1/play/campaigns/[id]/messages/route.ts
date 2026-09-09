import { requireBearerAuth } from "../../../../../lib/auth.js";
import {
  badRequest,
  created,
  forbidden,
  notFound,
  parseJsonBody,
} from "../../../../../lib/http.js";
import {
  createPlayCampaignMessage,
  getPlayCampaign,
  getPlayCampaignMember,
  type CreatePlayCampaignMessageInput,
} from "../../../../../lib/storage.js";

export const dynamic = "force-dynamic";

function isValidMessagePayload(
  body: Record<string, unknown>
): CreatePlayCampaignMessageInput | null {
  if (typeof body.text !== "string" || body.text.length === 0) {
    return null;
  }
  return { text: body.text };
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

  const isMember =
    campaign.owner === auth.user.username ||
    getPlayCampaignMember(id, auth.user.username) !== null;
  if (!isMember) {
    return forbidden();
  }

  const parsed = await parseJsonBody(req);
  if (!parsed.ok) return parsed.response;

  const payload = isValidMessagePayload(parsed.body);
  if (!payload) {
    return badRequest();
  }

  const result = createPlayCampaignMessage(id, auth.user.username, payload);
  if (!result) {
    return badRequest();
  }

  return created(result);
}
