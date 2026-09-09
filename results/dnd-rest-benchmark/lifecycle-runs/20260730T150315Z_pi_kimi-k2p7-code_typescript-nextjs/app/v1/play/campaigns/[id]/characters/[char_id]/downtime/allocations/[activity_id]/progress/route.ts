import { requireBearerAuth } from "../../../../../../../../../../lib/auth.js";
import {
  forbidden,
  notFound,
  ok,
} from "../../../../../../../../../../lib/http.js";
import {
  getCharacterOwner,
  getDowntimeActivity,
  getDowntimeAllocation,
  getPlayCampaign,
  progressDowntimeAllocation,
} from "../../../../../../../../../../lib/storage.js";

export const dynamic = "force-dynamic";

export async function POST(
  req: Request,
  {
    params,
  }: {
    params: Promise<{ id: string; char_id: string; activity_id: string }>;
  }
) {
  const auth = requireBearerAuth(req);
  if (!auth.ok) return auth.response;

  const { id, char_id, activity_id } = await params;

  const campaign = getPlayCampaign(id);
  if (!campaign) {
    return notFound();
  }

  const activity = getDowntimeActivity(id, activity_id);
  if (!activity) {
    return notFound();
  }

  const ownerRecord = getCharacterOwner(id, char_id);
  if (!ownerRecord) {
    return notFound();
  }

  const allocation = getDowntimeAllocation(id, char_id, activity_id);
  if (!allocation) {
    return notFound();
  }

  const isOwner = campaign.owner === auth.user.username;
  if (isOwner) {
    return forbidden();
  }

  if (!ownerRecord.owner || ownerRecord.owner !== auth.user.username) {
    return forbidden();
  }

  const result = progressDowntimeAllocation(id, char_id, activity_id);

  if (result === null) {
    return notFound();
  }

  return ok(result);
}
