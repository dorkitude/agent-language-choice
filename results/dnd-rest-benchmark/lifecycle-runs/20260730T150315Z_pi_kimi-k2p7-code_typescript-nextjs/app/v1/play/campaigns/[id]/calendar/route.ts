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
  createPlayCampaignCalendar,
  getPlayCampaign,
  getPlayCampaignCalendar,
  getPlayCampaignMembers,
} from "../../../../../lib/storage.js";
import { isInteger, isValidSeason } from "../../../../../lib/validate.js";

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
  if (!isInteger(b.day) || (b.day as number) < 1 || !isValidSeason(b.season)) {
    return badRequest();
  }

  const result = createPlayCampaignCalendar(id, b.day as number, b.season);
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

  const members = getPlayCampaignMembers(id);
  const isOwner = campaign.owner === auth.user.username;
  const member = members.find((m) => m.username === auth.user.username);

  if (!isOwner && !member) {
    return forbidden();
  }

  const calendar = getPlayCampaignCalendar(id);
  if (!calendar) {
    return notFound();
  }

  return ok(calendar);
}
