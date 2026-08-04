import { createMonster, hasMonster, Monster } from "../store.js";
import { parseJsonBody, requireNonEmptyString } from "../../http.js";

const SLUG_RE = /^[a-z0-9]+(-[a-z0-9]+)*$/;

export async function POST(request: Request) {
  const parsed = await parseJsonBody(request);
  if (!parsed.ok) return parsed.response;
  const body = parsed.body;

  const { slug, name, cr, armor_class, hit_points, tags } = (body ?? {}) as {
    slug?: unknown;
    name?: unknown;
    cr?: unknown;
    armor_class?: unknown;
    hit_points?: unknown;
    tags?: unknown;
  };

  if (typeof slug !== "string" || !SLUG_RE.test(slug)) {
    return Response.json(
      { error: "slug must be lowercase alphanumeric segments separated by hyphens" },
      { status: 400 },
    );
  }

  const validName = requireNonEmptyString(name, "name");
  if (validName instanceof Response) return validName;

  const validCr = requireNonEmptyString(cr, "cr");
  if (validCr instanceof Response) return validCr;

  if (typeof armor_class !== "number" || !Number.isFinite(armor_class)) {
    return Response.json({ error: "armor_class must be a number" }, { status: 400 });
  }

  if (typeof hit_points !== "number" || !Number.isFinite(hit_points)) {
    return Response.json({ error: "hit_points must be a number" }, { status: 400 });
  }

  let tagList: string[] = [];
  if (tags !== undefined) {
    if (!Array.isArray(tags) || !tags.every((tag) => typeof tag === "string")) {
      return Response.json({ error: "tags must be an array of strings" }, { status: 400 });
    }
    tagList = tags;
  }

  if (hasMonster(slug)) {
    return Response.json({ error: `monster ${slug} already exists` }, { status: 409 });
  }

  const monster: Monster = { slug, name: validName, cr: validCr, armor_class, hit_points, tags: tagList };
  createMonster(monster);

  return Response.json(
    {
      slug: monster.slug,
      name: monster.name,
      cr: monster.cr,
      armor_class: monster.armor_class,
      hit_points: monster.hit_points,
    },
    { status: 201 },
  );
}
