import { NextResponse } from "next/server";
import { createMonster, type CreateMonsterInput } from "../../../lib/storage.js";
import { badRequest, conflict, parseJsonBody } from "../../../lib/http.js";
import { isInteger, isNonEmptyString, isStringArray } from "../../../lib/validate.js";

export const dynamic = "force-dynamic";

function isValidMonsterBody(
  body: Record<string, unknown>
): body is Record<string, unknown> & CreateMonsterInput {
  if (!isNonEmptyString(body.slug)) return false;
  if (!isNonEmptyString(body.name)) return false;
  if (!isNonEmptyString(body.cr)) return false;
  if (!isInteger(body.armor_class)) return false;
  if (!isInteger(body.hit_points)) return false;
  if (!isStringArray(body.tags)) return false;
  return true;
}

export async function POST(req: Request) {
  const parsed = await parseJsonBody(req);
  if (!parsed.ok) return parsed.response;

  const b = parsed.body;
  if (!isValidMonsterBody(b)) {
    return badRequest();
  }

  const result = createMonster({
    slug: b.slug,
    name: b.name,
    cr: b.cr,
    armor_class: b.armor_class,
    hit_points: b.hit_points,
    tags: b.tags,
  });

  if (!result) {
    return conflict();
  }

  return NextResponse.json(
    {
      slug: result.slug,
      name: result.name,
      cr: result.cr,
      armor_class: result.armor_class,
      hit_points: result.hit_points,
    },
    { status: 201 }
  );
}
