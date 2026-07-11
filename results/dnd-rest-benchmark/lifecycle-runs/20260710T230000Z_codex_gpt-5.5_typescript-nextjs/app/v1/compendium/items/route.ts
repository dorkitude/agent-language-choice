import { badRequest, isRecord, json, readJson } from "../../../api.js";
import { isNonEmptyString, isNonNegativeInteger, isValidSlug, items, type Item } from "../data.js";

export const runtime = "nodejs";

export async function POST(request: Request) {
  const body = await readJson(request);
  if (
    !isRecord(body) ||
    !isValidSlug(body.slug) ||
    !isNonEmptyString(body.name) ||
    !isNonEmptyString(body.type) ||
    !isNonEmptyString(body.rarity) ||
    !isNonNegativeInteger(body.cost_gp)
  ) {
    return badRequest();
  }

  if (items.has(body.slug)) {
    return json({ error: "duplicate_slug" }, 409);
  }

  const item: Item = {
    slug: body.slug,
    name: body.name,
    type: body.type,
    rarity: body.rarity,
    cost_gp: body.cost_gp,
  };
  items.create(item);

  return json(item, 201);
}
