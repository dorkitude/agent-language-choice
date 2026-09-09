import { NextResponse } from "next/server";
import { revokePlayCampaignDelegation } from "../../../../../../lib/play-campaigns";
import { userRole } from "../../../../../../lib/users";

export const runtime = "nodejs";

function actor(request: Request): string | undefined {
  const value = request.headers.get("authorization");
  const prefix = "Bearer session-";
  return value?.startsWith(prefix) && value.length > prefix.length ? value.slice(prefix.length) : undefined;
}
function known(username: string): boolean {
  return username === "dm" || username === "player" || username === "player-a" || username === "player-b" || Boolean(userRole(username));
}

export async function DELETE(request: Request, { params }: { params: Promise<{ id: string; username: string }> }) {
  const who = actor(request);
  if (!who || !known(who)) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  const { id, username } = await params;
  const result = revokePlayCampaignDelegation(id, who, username);
  if (result.result === "revoked") return NextResponse.json(result.delegation);
  if (result.result === "forbidden") return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  return NextResponse.json({ error: "Delegation not found" }, { status: 404 });
}
