import { requireBearerAuth } from "../../../../../lib/auth.js";
import {
  badRequest,
  conflict,
  created,
  forbidden,
  internalServerError,
  notFound,
  ok,
  parseJsonBody,
} from "../../../../../lib/http.js";
import {
  createTransactionalTransfer,
  getPlayCampaign,
  getPlayCampaignMember,
  getTransactionalTransfers,
} from "../../../../../lib/storage.js";
import type { CreateTransactionalTransferInput } from "../../../../../lib/storage.js";
import { isNonEmptyString, isPositiveInteger } from "../../../../../lib/validate.js";

export const dynamic = "force-dynamic";

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

  const isOwner = campaign.owner === auth.user.username;
  if (!isOwner && !getPlayCampaignMember(id, auth.user.username)) {
    return forbidden();
  }

  const parsed = await parseJsonBody(req);
  if (!parsed.ok) return parsed.response;

  const b = parsed.body;
  if (
    !isNonEmptyString(b.from_character_id) ||
    !isNonEmptyString(b.to_character_id) ||
    !isPositiveInteger(b.amount) ||
    typeof b.simulate_failure !== "boolean"
  ) {
    return badRequest();
  }

  const input: CreateTransactionalTransferInput = {
    from_character_id: b.from_character_id,
    to_character_id: b.to_character_id,
    amount: b.amount,
    simulate_failure: b.simulate_failure,
  };

  const result = createTransactionalTransfer(id, input, auth.user.username);

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
  if (result === "simulated") {
    return internalServerError("simulated failure");
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

  const isOwner = campaign.owner === auth.user.username;
  if (!isOwner && !getPlayCampaignMember(id, auth.user.username)) {
    return forbidden();
  }

  const transfers = getTransactionalTransfers(id);
  return ok({ transfers });
}
