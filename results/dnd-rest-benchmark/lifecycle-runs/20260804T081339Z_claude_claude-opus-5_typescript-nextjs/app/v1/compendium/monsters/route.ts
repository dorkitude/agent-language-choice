import {
  getMonster,
  insertMonster,
  isValidCr,
  parseTags,
} from "../../../../lib/compendium";
import { badRequest, conflict, json, readObject } from "../../../../lib/http";
import { asCount, isNonEmptyString, isValidSlug } from "../../../../lib/validation";

export const dynamic = "force-dynamic";

export async function POST(request: Request): Promise<Response> {
  const body = await readObject(request);
  if (!body) return badRequest("body must be a JSON object");

  const { slug, name, cr, armor_class, hit_points } = body;
  if (!isValidSlug(slug)) return badRequest("slug must be 1-64 characters of [A-Za-z0-9_-]");
  if (!isNonEmptyString(name)) return badRequest("name must be a non-empty string");
  if (!isValidCr(cr)) return badRequest("cr must be a number or a fraction such as '1/4'");

  const armorClass = asCount(armor_class, 0);
  if (armorClass === undefined) return badRequest("armor_class must be a non-negative integer");

  const hitPoints = asCount(hit_points, 1);
  if (hitPoints === undefined) return badRequest("hit_points must be a positive integer");

  const tags = parseTags(body.tags);
  if (!tags) return badRequest("tags must be an array of non-empty strings");

  if (getMonster(slug)) return conflict("monster slug already exists");

  insertMonster({
    slug,
    name,
    cr,
    armor_class: armorClass,
    hit_points: hitPoints,
    tags,
  });

  return json(
    { slug, name, cr, armor_class: armorClass, hit_points: hitPoints },
    201,
  );
}
