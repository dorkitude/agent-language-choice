import { NextResponse } from "next/server";
import { badRequest } from "../../../../../../../../../lib/http";
import { attunePlayCampaignCharacterEquipment, isPlayCampaignEquipmentSlot } from "../../../../../../../../../lib/play-campaigns";
import { userRole } from "../../../../../../../../../lib/users";

export const runtime = "nodejs";

function actorFromAuthorization(request: Request): string | undefined {
  const authorization = request.headers.get("authorization");
  const prefix = "Bearer session-";
  if (!authorization?.startsWith(prefix)) return undefined;
  const username = authorization.slice(prefix.length);
  return username.length > 0 ? username : undefined;
}

function knownActor(actor: string): boolean {
  return actor === "dm" || actor === "player" || actor === "player-a" || actor === "player-b" || Boolean(userRole(actor));
}

export async function POST(request: Request, { params }: { params: Promise<{ id: string; char_id: string; slot: string }> }) {
  const actor = actorFromAuthorization(request);
  if (!actor || !knownActor(actor)) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  const { id, char_id, slot } = await params;
  if (!isPlayCampaignEquipmentSlot(slot)) return badRequest();
  const result = attunePlayCampaignCharacterEquipment(id, char_id, actor, slot);
  if (result.result === "attuned") return NextResponse.json(result.equipment);
  if (result.result === "invalid") return badRequest();
  if (result.result === "conflict") return NextResponse.json({ error: "Attunement limit reached" }, { status: 409 });
  if (result.result === "forbidden") return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  return NextResponse.json({ error: "Campaign or character not found" }, { status: 404 });
}
