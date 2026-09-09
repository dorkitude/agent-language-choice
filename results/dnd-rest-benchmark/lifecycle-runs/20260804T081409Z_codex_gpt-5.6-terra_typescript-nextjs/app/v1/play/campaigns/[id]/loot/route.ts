import { NextResponse } from "next/server";
import { badRequest, isInteger, isNonEmptyString, isRecord, jsonBody } from "../../../../../lib/http";
import { createPlayCampaignLoot, isPlayCampaignInventoryItemId } from "../../../../../lib/play-campaigns";
import { userRole } from "../../../../../lib/users";

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

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const actor = actorFromAuthorization(request);
  if (!actor || !roleForActor(actor)) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  const body = await jsonBody(request);
  if (!isRecord(body) || !isNonEmptyString(body.loot_id) || !isNonEmptyString(body.item_id) ||
    !isPlayCampaignInventoryItemId(body.item_id) || !isInteger(body.quantity) || body.quantity <= 0) return badRequest();

  const { id } = await params;
  const result = createPlayCampaignLoot(id, actor, { loot_id: body.loot_id, item_id: body.item_id, quantity: body.quantity });
  if (result.result === "created") return NextResponse.json(result.loot, { status: 201 });
  if (result.result === "forbidden") return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  if (result.result === "conflict") return NextResponse.json({ error: "Loot already exists" }, { status: 409 });
  return NextResponse.json({ error: "Campaign not found" }, { status: 404 });
}
