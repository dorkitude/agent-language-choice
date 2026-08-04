import { requireBearerAuth } from "../../../../../../../lib/auth.js";
import {
  badRequest,
  conflict,
  created,
  forbidden,
  notFound,
  parseJsonBody,
} from "../../../../../../../lib/http.js";
import {
  bindMemberToEncounter,
  getPlayCampaign,
  getPlayCampaignEncounter,
  getPlayCampaignMembers,
} from "../../../../../../../lib/storage.js";
import { isInteger, isNonEmptyString } from "../../../../../../../lib/validate.js";

export const dynamic = "force-dynamic";

export async function POST(
  req: Request,
  { params }: { params: Promise<{ id: string; enc_id: string }> }
) {
  const auth = requireBearerAuth(req, "dm");
  if (!auth.ok) return auth.response;

  const { id, enc_id } = await params;

  const campaign = getPlayCampaign(id);
  if (!campaign) {
    return notFound();
  }

  if (campaign.owner !== auth.user.username) {
    return forbidden();
  }

  const encounter = getPlayCampaignEncounter(id, enc_id);
  if (!encounter) {
    return notFound();
  }

  const parsed = await parseJsonBody(req);
  if (!parsed.ok) return parsed.response;

  const b = parsed.body;
  if (!isNonEmptyString(b.member) || !isInteger(b.initiative)) {
    return badRequest();
  }

  const members = getPlayCampaignMembers(id);
  const member = members.find((m) => m.username === b.member);
  if (!member) {
    return badRequest();
  }

  const result = bindMemberToEncounter(
    id,
    enc_id,
    b.member,
    member.character_id,
    member.name,
    b.initiative
  );
  if (!result) {
    return conflict();
  }

  return created(result);
}
