import { NextResponse } from "next/server";
import { readPlayCampaignCharacterSheet } from "../../../../../../../lib/play-campaigns";
import { userRole } from "../../../../../../../lib/users";

export const runtime = "nodejs";

function actor(request: Request) {
  const value = request.headers.get("authorization");
  const prefix = "Bearer session-";
  return value?.startsWith(prefix) && value.length > prefix.length ? value.slice(prefix.length) : undefined;
}

function known(value: string) {
  return value === "dm" || value === "player" || value === "player-a" || value === "player-b" || Boolean(userRole(value));
}

export async function GET(request: Request, { params }: { params: Promise<{ id: string; char_id: string }> }) {
  const who = actor(request);
  if (!who || !known(who)) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  const { id, char_id } = await params;
  const result = readPlayCampaignCharacterSheet(id, char_id, who);
  if (result.result === "found") return NextResponse.json(result.sheet);
  return NextResponse.json(
    { error: result.result === "forbidden" ? "Forbidden" : "Campaign or character not found" },
    { status: result.result === "forbidden" ? 403 : 404 },
  );
}
