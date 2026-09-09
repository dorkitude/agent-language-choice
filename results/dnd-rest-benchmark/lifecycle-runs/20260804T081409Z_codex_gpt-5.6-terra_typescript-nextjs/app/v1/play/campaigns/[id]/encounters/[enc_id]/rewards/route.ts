import { NextResponse } from "next/server";
import { badRequest, isInteger, isNonEmptyString, isRecord, jsonBody } from "../../../../../../../lib/http";
import { awardPlayCampaignEncounterRewards, type PlayCampaignEncounterLoot } from "../../../../../../../lib/play-campaigns";
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

function isLoot(value: unknown): value is PlayCampaignEncounterLoot[] {
  return Array.isArray(value) && value.every((entry) =>
    isRecord(entry) && isNonEmptyString(entry.slug) && isInteger(entry.quantity) && entry.quantity > 0,
  );
}

export async function POST(request: Request, { params }: { params: Promise<{ id: string; enc_id: string }> }) {
  const actor = actorFromAuthorization(request);
  if (!actor || !roleForActor(actor)) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  if (roleForActor(actor) !== "dm") return NextResponse.json({ error: "Forbidden" }, { status: 403 });

  const body = await jsonBody(request);
  if (!isRecord(body) || !isInteger(body.xp) || body.xp < 0 || !isLoot(body.loot)) return badRequest();

  const { id, enc_id } = await params;
  const result = awardPlayCampaignEncounterRewards(id, enc_id, actor, { xp: body.xp, loot: body.loot });
  if (result.result === "awarded") return NextResponse.json(result.reward);
  if (result.result === "not_found") return NextResponse.json({ error: "Campaign or encounter not found" }, { status: 404 });
  if (result.result === "forbidden") return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  return NextResponse.json({ error: "Rewards already awarded" }, { status: 409 });
}
