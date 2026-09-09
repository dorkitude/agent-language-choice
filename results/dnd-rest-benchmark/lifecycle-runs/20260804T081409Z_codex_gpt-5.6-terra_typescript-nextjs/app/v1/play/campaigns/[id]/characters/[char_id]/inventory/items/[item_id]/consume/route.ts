import { NextResponse } from "next/server";
import { badRequest } from "../../../../../../../../../../lib/http";
import {
  consumePlayCampaignCharacterInventoryItem,
  isPlayCampaignConsumableItemId,
} from "../../../../../../../../../../lib/play-campaigns";
import { userRole } from "../../../../../../../../../../lib/users";

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

export async function POST(request: Request, { params }: { params: Promise<{ id: string; char_id: string; item_id: string }> }) {
  const actor = actorFromAuthorization(request);
  if (!actor || !knownActor(actor)) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  const { id, char_id, item_id } = await params;
  if (!isPlayCampaignConsumableItemId(item_id)) return badRequest();

  const result = consumePlayCampaignCharacterInventoryItem(id, char_id, actor, item_id);
  if (result.result === "consumed") {
    return NextResponse.json({
      character_id: result.item.character_id,
      item_id: result.item.item_id,
      quantity_consumed: 1,
      total_quantity: result.item.total_quantity,
      effect: { type: "healing", hp_restored: 5 },
    });
  }
  if (result.result === "invalid") return badRequest();
  if (result.result === "forbidden") return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  if (result.result === "insufficient") return NextResponse.json({ error: "Insufficient item quantity" }, { status: 409 });
  return NextResponse.json({ error: "Campaign or character not found" }, { status: 404 });
}
