import { NextResponse } from "next/server";
import { badRequest, isInteger, isNonEmptyString, isRecord, jsonBody } from "../../../../../../../lib/http";
import { createPlayCampaignShop, isPlayCampaignInventoryItemId, type PlayCampaignShop } from "../../../../../../../lib/play-campaigns";
import { userRole } from "../../../../../../../lib/users";

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

function shopFromBody(body: unknown): PlayCampaignShop | undefined {
  if (!isRecord(body) || !isNonEmptyString(body.shop_id) || !isNonEmptyString(body.name) ||
    !isRecord(body.stock) || !isInteger(body.buy_price) || body.buy_price <= 0 ||
    !isInteger(body.sell_price) || body.sell_price < 0) return undefined;
  const entries = Object.entries(body.stock);
  if (entries.length === 0 || entries.some(([itemId, quantity]) => !isPlayCampaignInventoryItemId(itemId) || !isInteger(quantity) || quantity <= 0)) return undefined;
  const stock: Record<string, number> = {};
  for (const [itemId, quantity] of entries) stock[itemId] = quantity as number;
  return { shop_id: body.shop_id, name: body.name, stock, buy_price: body.buy_price, sell_price: body.sell_price };
}

export async function POST(request: Request, { params }: { params: Promise<{ id: string; settlement_id: string }> }) {
  const actor = actorFromAuthorization(request);
  if (!actor || !roleForActor(actor)) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  if (roleForActor(actor) !== "dm") return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  const shop = shopFromBody(await jsonBody(request));
  if (!shop) return badRequest();
  const { id, settlement_id } = await params;
  const result = createPlayCampaignShop(id, settlement_id, actor, shop);
  if (result.result === "created") return NextResponse.json(result.shop, { status: 201 });
  if (result.result === "forbidden") return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  if (result.result === "conflict") return NextResponse.json({ error: "Shop already exists" }, { status: 409 });
  return NextResponse.json({ error: "Campaign or settlement not found" }, { status: 404 });
}
