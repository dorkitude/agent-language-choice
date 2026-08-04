import { NextResponse } from "next/server";
import { createMonster, type Monster } from "../../../lib/compendium";
import { badRequest, isInteger, isRecord, jsonBody } from "../../../lib/http";

export const runtime = "nodejs";

function isNonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.length > 0;
}

export async function POST(request: Request) {
  const body = await jsonBody(request);
  if (
    !isRecord(body) ||
    !isNonEmptyString(body.slug) ||
    !isNonEmptyString(body.name) ||
    !isNonEmptyString(body.cr) ||
    !isInteger(body.armor_class) || body.armor_class < 0 ||
    !isInteger(body.hit_points) || body.hit_points < 0 ||
    !Array.isArray(body.tags) || !body.tags.every(isNonEmptyString)
  ) {
    return badRequest();
  }

  const monster: Monster = {
    slug: body.slug,
    name: body.name,
    cr: body.cr,
    armor_class: body.armor_class,
    hit_points: body.hit_points,
    tags: body.tags,
  };
  if (!createMonster(monster)) return NextResponse.json({ error: "Monster slug already exists" }, { status: 409 });

  const { tags: _tags, ...response } = monster;
  return NextResponse.json(response, { status: 201 });
}
