import { getItem, insertItem } from "../../../../lib/compendium";
import { badRequest, conflict, json, readObject } from "../../../../lib/http";
import { asCount, isNonEmptyString, isValidSlug } from "../../../../lib/validation";

export const dynamic = "force-dynamic";

export async function POST(request: Request): Promise<Response> {
  const body = await readObject(request);
  if (!body) return badRequest("body must be a JSON object");

  const { slug, name, type, rarity, cost_gp } = body;
  if (!isValidSlug(slug)) return badRequest("slug must be 1-64 characters of [A-Za-z0-9_-]");
  if (!isNonEmptyString(name)) return badRequest("name must be a non-empty string");
  if (!isNonEmptyString(type)) return badRequest("type must be a non-empty string");
  if (!isNonEmptyString(rarity)) return badRequest("rarity must be a non-empty string");

  const cost = asCount(cost_gp, 0);
  if (cost === undefined) return badRequest("cost_gp must be a non-negative integer");

  if (getItem(slug)) return conflict("item slug already exists");

  insertItem({ slug, name, type, rarity, cost_gp: cost });
  return json({ slug, name, type, rarity, cost_gp: cost }, 201);
}
