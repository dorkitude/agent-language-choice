import { NextResponse } from "next/server";
import { createItem, type CreateItemInput } from "../../../lib/storage.js";
import { badRequest, conflict, parseJsonBody } from "../../../lib/http.js";
import { isInteger, isNonEmptyString } from "../../../lib/validate.js";

export const dynamic = "force-dynamic";

function isValidItemBody(
  body: Record<string, unknown>
): body is Record<string, unknown> & CreateItemInput {
  if (!isNonEmptyString(body.slug)) return false;
  if (!isNonEmptyString(body.name)) return false;
  if (!isNonEmptyString(body.type)) return false;
  if (!isNonEmptyString(body.rarity)) return false;
  if (!isInteger(body.cost_gp)) return false;
  return true;
}

export async function POST(req: Request) {
  const parsed = await parseJsonBody(req);
  if (!parsed.ok) return parsed.response;

  const b = parsed.body;
  if (!isValidItemBody(b)) {
    return badRequest();
  }

  const result = createItem({
    slug: b.slug,
    name: b.name,
    type: b.type,
    rarity: b.rarity,
    cost_gp: b.cost_gp,
  });

  if (!result) {
    return conflict();
  }

  return NextResponse.json(result, { status: 201 });
}
