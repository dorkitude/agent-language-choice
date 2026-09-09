import { NextResponse } from "next/server";
import { badRequest, isInteger, isNonEmptyString, isRecord, jsonBody } from "../../../../../../../../lib/http";
import {
  addPlayCampaignCharacterInventoryItem,
  isPlayCampaignInventoryItemId,
  readPlayCampaignCharacterInventoryItems,
} from "../../../../../../../../lib/play-campaigns";
import { userRole } from "../../../../../../../../lib/users";

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

export async function POST(request: Request, { params }: { params: Promise<{ id: string; char_id: string }> }) {
  const actor = actorFromAuthorization(request);
  if (!actor || !knownActor(actor)) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  const body = await jsonBody(request);
  if (
    !isRecord(body) || !isNonEmptyString(body.item_id) || !isPlayCampaignInventoryItemId(body.item_id) ||
    !isInteger(body.quantity) || body.quantity <= 0
  ) return badRequest();

  const { id, char_id } = await params;
  const result = addPlayCampaignCharacterInventoryItem(id, char_id, actor, body.item_id, body.quantity);
  if (result.result === "created") return NextResponse.json(result.item, { status: 201 });
  if (result.result === "forbidden") return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  return NextResponse.json({ error: "Campaign or character not found" }, { status: 404 });
}

export async function GET(request: Request, { params }: { params: Promise<{ id: string; char_id: string }> }) {
  const actor = actorFromAuthorization(request);
  if (!actor || !knownActor(actor)) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  const { id, char_id } = await params;
  const result = readPlayCampaignCharacterInventoryItems(id, char_id, actor);
  if (result.result === "found") return NextResponse.json(result.inventory);
  if (result.result === "forbidden") return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  return NextResponse.json({ error: "Campaign or character not found" }, { status: 404 });
}
