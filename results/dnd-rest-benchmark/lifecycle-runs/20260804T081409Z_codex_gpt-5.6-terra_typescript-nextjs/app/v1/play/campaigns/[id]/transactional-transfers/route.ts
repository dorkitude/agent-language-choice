import { NextResponse } from "next/server";
import { badRequest, isInteger, isNonEmptyString, isRecord, jsonBody } from "../../../../../lib/http";
import { createPlayCampaignTransactionalTransfer, readPlayCampaignTransactionalTransfers } from "../../../../../lib/play-campaigns";

export const runtime = "nodejs";

function actorFromAuthorization(request: Request): string | undefined {
  const authorization = request.headers.get("authorization");
  const prefix = "Bearer session-";
  if (!authorization?.startsWith(prefix)) return undefined;
  const username = authorization.slice(prefix.length);
  return username.length > 0 ? username : undefined;
}

function unauthorized() {
  return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
}

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const actor = actorFromAuthorization(request);
  if (!actor) return unauthorized();
  const body = await jsonBody(request);
  if (!isRecord(body) || !isNonEmptyString(body.from_character_id) || !isNonEmptyString(body.to_character_id) ||
    !isInteger(body.amount) || body.amount <= 0 || typeof body.simulate_failure !== "boolean") return badRequest();

  const result = createPlayCampaignTransactionalTransfer((await params).id, actor, {
    from_character_id: body.from_character_id,
    to_character_id: body.to_character_id,
    amount: body.amount,
    simulate_failure: body.simulate_failure,
  });
  if (result.result === "created") return NextResponse.json(result.transfer, { status: 201 });
  if (result.result === "simulated_failure") return NextResponse.json({ error: "simulated failure" }, { status: 500 });
  if (result.result === "forbidden") return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  if (result.result === "invalid") return badRequest();
  if (result.result === "insufficient") return NextResponse.json({ error: "Insufficient gold" }, { status: 409 });
  return NextResponse.json({ error: "Campaign not found" }, { status: 404 });
}

export async function GET(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const actor = actorFromAuthorization(request);
  if (!actor) return unauthorized();
  const result = readPlayCampaignTransactionalTransfers((await params).id, actor);
  if (result.result === "found") return NextResponse.json({ transfers: result.transfers });
  if (result.result === "forbidden") return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  return NextResponse.json({ error: "Campaign not found" }, { status: 404 });
}
