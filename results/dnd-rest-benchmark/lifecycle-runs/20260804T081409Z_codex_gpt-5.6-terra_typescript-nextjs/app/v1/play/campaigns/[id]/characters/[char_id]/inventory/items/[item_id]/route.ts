import { NextResponse } from "next/server";
import { badRequest, isInteger, isRecord, jsonBody } from "../../../../../../../../../lib/http";
import { isPlayCampaignInventoryItemId, removePlayCampaignCharacterInventoryItem } from "../../../../../../../../../lib/play-campaigns";
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

export async function DELETE(request: Request, { params }: { params: Promise<{ id: string; char_id: string; item_id: string }> }) {
  const actor = actorFromAuthorization(request);
  if (!actor || !knownActor(actor)) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  const body = await jsonBody(request);
  const { id, char_id, item_id } = await params;
  if (!isRecord(body) || !isInteger(body.quantity) || body.quantity <= 0 || !isPlayCampaignInventoryItemId(item_id)) return badRequest();

  const result = removePlayCampaignCharacterInventoryItem(id, char_id, actor, item_id, body.quantity);
  if (result.result === "removed") return NextResponse.json(result.item);
  if (result.result === "forbidden") return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  if (result.result === "insufficient") return NextResponse.json({ error: "Insufficient item quantity" }, { status: 409 });
  return NextResponse.json({ error: "Campaign or character not found" }, { status: 404 });
}
