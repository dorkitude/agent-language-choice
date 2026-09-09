import { NextResponse } from "next/server";
import { badRequest, isInteger, isNonEmptyString, isRecord, jsonBody } from "../../../../../../../../../lib/http";
import { isPlayCampaignInventoryItemId, tradePlayCampaignShop } from "../../../../../../../../../lib/play-campaigns";
import { userRole } from "../../../../../../../../../lib/users";

export const runtime = "nodejs";

function actorFromAuthorization(request: Request): string | undefined {
  const authorization = request.headers.get("authorization");
  const prefix = "Bearer session-";
  if (!authorization?.startsWith(prefix)) return undefined;
  const username = authorization.slice(prefix.length);
  return username.length > 0 ? username : undefined;
}

function roleForActor(actor: string): "dm" | "player" | undefined {
  if (actor === "dm") return "dm";
  if (actor === "player" || actor === "player-a" || actor === "player-b") return "player";
  return userRole(actor);
}

export async function POST(request: Request, { params }: { params: Promise<{ id: string; settlement_id: string; shop_id: string }> }) {
  const actor = actorFromAuthorization(request);
  if (!actor || !roleForActor(actor)) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  if (roleForActor(actor) !== "player") return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  const body = await jsonBody(request);
  if (!isRecord(body) || !isNonEmptyString(body.character_id) || !isNonEmptyString(body.item_id) ||
    !isPlayCampaignInventoryItemId(body.item_id) || !isInteger(body.quantity) || body.quantity <= 0) return badRequest();
  const { id, settlement_id, shop_id } = await params;
  const result = tradePlayCampaignShop(id, settlement_id, shop_id, actor, body.character_id, body.item_id, body.quantity, "buy");
  if (result.result === "traded") return NextResponse.json(result.trade);
  if (result.result === "forbidden") return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  if (result.result === "insufficient") return NextResponse.json({ error: "Insufficient stock or gold" }, { status: 409 });
  return NextResponse.json({ error: "Campaign, settlement, shop, or character not found" }, { status: 404 });
}
