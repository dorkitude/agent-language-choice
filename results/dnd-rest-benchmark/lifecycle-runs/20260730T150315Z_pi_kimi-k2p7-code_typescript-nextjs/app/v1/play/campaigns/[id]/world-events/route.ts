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
  createPlayCampaignWorldEvent,
  getPlayCampaign,
  getPlayCampaignMembers,
  getPlayCampaignWorldEvents,
} from "../../../../../lib/storage.js";
import {
  isInteger,
  isNonEmptyString,
} from "../../../../../lib/validate.js";

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
  if (
    !isNonEmptyString(b.event_id) ||
    !isNonEmptyString(b.title) ||
    !isNonEmptyString(b.text) ||
    !isInteger(b.turn_number)
  ) {
    return badRequest();
  }

  const result = createPlayCampaignWorldEvent(id, {
    event_id: b.event_id,
    turn_number: b.turn_number as number,
    title: b.title,
    text: b.text,
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

  return ok({ events: getPlayCampaignWorldEvents(id) });
}
