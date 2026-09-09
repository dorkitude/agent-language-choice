import { requireBearerAuth } from "../../../../../../../../lib/auth.js";
import {
  badRequest,
  conflict,
  created,
  forbidden,
  notFound,
  parseJsonBody,
} from "../../../../../../../../lib/http.js";
import {
  createDowntimeAllocation,
  getCharacterOwner,
  getDowntimeActivity,
  getPlayCampaign,
} from "../../../../../../../../lib/storage.js";
import { isNonEmptyString } from "../../../../../../../../lib/validate.js";

export const dynamic = "force-dynamic";

export async function POST(
  req: Request,
  { params }: { params: Promise<{ id: string; char_id: string }> }
) {
  const auth = requireBearerAuth(req);
  if (!auth.ok) return auth.response;

  const { id, char_id } = await params;

  const campaign = getPlayCampaign(id);
  if (!campaign) {
    return notFound();
  }

  const parsed = await parseJsonBody(req);
  if (!parsed.ok) return parsed.response;

  const b = parsed.body;
  if (!isNonEmptyString(b.activity_id)) {
    return badRequest();
  }
  const activityId = b.activity_id as string;

  const activity = getDowntimeActivity(id, activityId);
  if (!activity) {
    return notFound();
  }

  const ownerRecord = getCharacterOwner(id, char_id);
  if (!ownerRecord) {
    return notFound();
  }

  const isOwner = campaign.owner === auth.user.username;
  if (isOwner) {
    return forbidden();
  }

  if (!ownerRecord.owner || ownerRecord.owner !== auth.user.username) {
    return forbidden();
  }

  const result = createDowntimeAllocation(id, char_id, activityId);

  if (result === null) {
    return notFound();
  }
  if (result === "conflict") {
    return conflict();
  }

  return created(result);
}
