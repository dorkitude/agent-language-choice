import { NextResponse } from "next/server";
import { createItem, type Item } from "../../../lib/compendium";
import { badRequest, isNonEmptyString, isRecord, jsonBody } from "../../../lib/http";

export const runtime = "nodejs";

export async function POST(request: Request) {
  const body = await jsonBody(request);
  if (
    !isRecord(body) ||
    !isNonEmptyString(body.slug) ||
    !isNonEmptyString(body.name) ||
    !isNonEmptyString(body.type) ||
    !isNonEmptyString(body.rarity) ||
    typeof body.cost_gp !== "number" || !Number.isFinite(body.cost_gp) || body.cost_gp < 0
  ) {
    return badRequest();
  }

  const item: Item = {
    slug: body.slug,
    name: body.name,
    type: body.type,
    rarity: body.rarity,
    cost_gp: body.cost_gp,
  };
  if (!createItem(item)) return NextResponse.json({ error: "Item slug already exists" }, { status: 409 });
  return NextResponse.json(item, { status: 201 });
}
