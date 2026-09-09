import { NextResponse } from "next/server";
import { badRequest, isNonEmptyString, isRecord, jsonBody } from "../../../../../lib/http";
import { grantPlayCampaignDelegation } from "../../../../../lib/play-campaigns";
import { userRole } from "../../../../../lib/users";

export const runtime = "nodejs";

function actor(request: Request): string | undefined {
  const value = request.headers.get("authorization");
  const prefix = "Bearer session-";
  return value?.startsWith(prefix) && value.length > prefix.length ? value.slice(prefix.length) : undefined;
}

function known(username: string): boolean {
  return username === "dm" || username === "player" || username === "player-a" || username === "player-b" || Boolean(userRole(username));
}

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const who = actor(request);
  if (!who || !known(who)) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  const body = await jsonBody(request);
  if (!isRecord(body) || !isNonEmptyString(body.username) || !Array.isArray(body.powers)
    || body.powers.length !== 1 || body.powers[0] !== "narrate") return badRequest();
  const result = grantPlayCampaignDelegation((await params).id, who, body.username);
  if (result.result === "created") return NextResponse.json(result.delegation, { status: 201 });
  if (result.result === "not_found") return NextResponse.json({ error: "Campaign not found" }, { status: 404 });
  if (result.result === "forbidden") return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  if (result.result === "conflict") return NextResponse.json({ error: "Delegation already active" }, { status: 409 });
  return badRequest();
}
