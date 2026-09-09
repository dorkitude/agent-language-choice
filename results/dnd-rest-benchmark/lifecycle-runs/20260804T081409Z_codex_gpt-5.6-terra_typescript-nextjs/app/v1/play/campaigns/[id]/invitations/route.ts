import { NextResponse } from "next/server";
import { badRequest, isNonEmptyString, isRecord, jsonBody } from "../../../../../lib/http";
import { createPlayCampaignInvitation, readPlayCampaignInvitations } from "../../../../../lib/play-campaigns";
import { userRole } from "../../../../../lib/users";

export const runtime = "nodejs";

function actor(request: Request): string | undefined {
  const value = request.headers.get("authorization");
  const prefix = "Bearer session-";
  return value?.startsWith(prefix) && value.length > prefix.length ? value.slice(prefix.length) : undefined;
}
function known(value: string) { return value === "dm" || value === "player" || value === "player-a" || value === "player-b" || Boolean(userRole(value)); }
function unauthorized() { return NextResponse.json({ error: "Unauthorized" }, { status: 401 }); }

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const who = actor(request);
  if (!who || !known(who)) return unauthorized();
  const body = await jsonBody(request);
  if (!isRecord(body) || !isNonEmptyString(body.invitation_id) || !isNonEmptyString(body.username) || !isNonEmptyString(body.character_id)) return badRequest();
  if (userRole(body.username) !== "player") return badRequest();
  const result = createPlayCampaignInvitation((await params).id, who, {
    invitation_id: body.invitation_id,
    username: body.username,
    character_id: body.character_id,
  });
  if (result.result === "created") return NextResponse.json(result.invitation, { status: 201 });
  if (result.result === "forbidden") return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  return NextResponse.json({ error: result.result === "conflict" ? "Invitation already exists" : "Campaign not found" }, { status: result.result === "conflict" ? 409 : 404 });
}

export async function GET(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const who = actor(request);
  if (!who || !known(who)) return unauthorized();
  const result = readPlayCampaignInvitations((await params).id, who);
  if (result.result === "found") return NextResponse.json({ invitations: result.invitations });
  return NextResponse.json({ error: "Campaign not found" }, { status: 404 });
}
