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
  getPlayCampaign,
  transferCurrency,
} from "../../../../../../../../lib/storage.js";

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
  if (
    typeof b.to_character_id !== "string" ||
    b.to_character_id.length === 0 ||
    !Number.isInteger(b.gold) ||
    (b.gold as number) < 1
  ) {
    return badRequest();
  }

  const result = transferCurrency(
    id,
    char_id,
    b.to_character_id,
    b.gold as number,
    auth.user.username
  );

  if (result === "not_found") {
    return notFound();
  }
  if (result === "forbidden") {
    return forbidden();
  }
  if (result === "invalid") {
    return badRequest();
  }
  if (result === "insufficient") {
    return conflict();
  }

  return created({
    from_character_id: result.from_character_id,
    to_character_id: result.to_character_id,
    gold: result.gold,
    from_gold: result.from_gold,
    to_gold: result.to_gold,
    transfer_id: result.transfer_id,
  });
}
