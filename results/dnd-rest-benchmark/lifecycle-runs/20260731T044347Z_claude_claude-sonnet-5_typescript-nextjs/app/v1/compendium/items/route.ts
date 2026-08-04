import { createItem, hasItem, Item } from "../store.js";
import { parseJsonBody, requireNonEmptyString } from "../../http.js";

const SLUG_RE = /^[a-z0-9]+(-[a-z0-9]+)*$/;

export async function POST(request: Request) {
  const parsed = await parseJsonBody(request);
  if (!parsed.ok) return parsed.response;
  const body = parsed.body;

  const { slug, name, type, rarity, cost_gp } = (body ?? {}) as {
    slug?: unknown;
    name?: unknown;
    type?: unknown;
    rarity?: unknown;
    cost_gp?: unknown;
  };

  if (typeof slug !== "string" || !SLUG_RE.test(slug)) {
    return Response.json(
      { error: "slug must be lowercase alphanumeric segments separated by hyphens" },
      { status: 400 },
    );
  }

  const validName = requireNonEmptyString(name, "name");
  if (validName instanceof Response) return validName;

  const validType = requireNonEmptyString(type, "type");
  if (validType instanceof Response) return validType;

  const validRarity = requireNonEmptyString(rarity, "rarity");
  if (validRarity instanceof Response) return validRarity;

  if (typeof cost_gp !== "number" || !Number.isFinite(cost_gp)) {
    return Response.json({ error: "cost_gp must be a number" }, { status: 400 });
  }

  if (hasItem(slug)) {
    return Response.json({ error: `item ${slug} already exists` }, { status: 409 });
  }

  const item: Item = { slug, name: validName, type: validType, rarity: validRarity, cost_gp };
  createItem(item);

  return Response.json(item, { status: 201 });
}
