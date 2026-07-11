import { badRequest, isRecord, json, readJson } from "../../../api.js";
import {
  isNonEmptyString,
  isPositiveInteger,
  isTags,
  isValidSlug,
  monsterCreateResponse,
  monsters,
  type Monster,
} from "../data.js";

export const runtime = "nodejs";

export async function POST(request: Request) {
  const body = await readJson(request);
  if (
    !isRecord(body) ||
    !isValidSlug(body.slug) ||
    !isNonEmptyString(body.name) ||
    !isNonEmptyString(body.cr) ||
    !isPositiveInteger(body.armor_class) ||
    !isPositiveInteger(body.hit_points) ||
    !isTags(body.tags)
  ) {
    return badRequest();
  }

  if (monsters.has(body.slug)) {
    return json({ error: "duplicate_slug" }, 409);
  }

  const monster: Monster = {
    slug: body.slug,
    name: body.name,
    cr: body.cr,
    armor_class: body.armor_class,
    hit_points: body.hit_points,
    tags: body.tags,
  };
  monsters.create(monster);

  return json(monsterCreateResponse(monster), 201);
}
