// Monster and item reference data (create + lookup by slug). `getMonster`
// is also used by routes/dm.ts to resolve monster slugs for encounter
// building.
import type { ServerResponse } from "node:http";
import { db } from "../db.js";
import { sendJson } from "../http.js";
import { isPlainObject, isValidInt, SLUG_RE } from "../validation.js";

export interface MonsterRecord {
  slug: string;
  name: string;
  cr: string;
  armorClass: number;
  hitPoints: number;
  tags: string[];
}

function hasMonster(slug: string): boolean {
  const row = db.prepare("SELECT 1 FROM monsters WHERE slug = ?").get(slug);
  return row !== undefined;
}

export function getMonster(slug: string): MonsterRecord | undefined {
  const row = db
    .prepare("SELECT slug, name, cr, armor_class, hit_points, tags FROM monsters WHERE slug = ?")
    .get(slug) as
    | { slug: string; name: string; cr: string; armor_class: number; hit_points: number; tags: string }
    | undefined;
  if (!row) return undefined;
  return {
    slug: row.slug,
    name: row.name,
    cr: row.cr,
    armorClass: row.armor_class,
    hitPoints: row.hit_points,
    tags: JSON.parse(row.tags) as string[],
  };
}

function saveMonster(monster: MonsterRecord): void {
  db.prepare(
    "INSERT INTO monsters (slug, name, cr, armor_class, hit_points, tags) VALUES (?, ?, ?, ?, ?, ?)",
  ).run(monster.slug, monster.name, monster.cr, monster.armorClass, monster.hitPoints, JSON.stringify(monster.tags));
}

export function handleCreateMonster(res: ServerResponse, body: unknown): void {
  if (
    !isPlainObject(body) ||
    typeof body.slug !== "string" ||
    typeof body.name !== "string" ||
    typeof body.cr !== "string" ||
    !isValidInt(body.armor_class, 0, Number.MAX_SAFE_INTEGER) ||
    !isValidInt(body.hit_points, 0, Number.MAX_SAFE_INTEGER) ||
    !Array.isArray(body.tags) ||
    !body.tags.every((tag) => typeof tag === "string")
  ) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  if (!SLUG_RE.test(body.slug)) {
    sendJson(res, 400, { error: "invalid slug" });
    return;
  }

  if (hasMonster(body.slug)) {
    sendJson(res, 409, { error: "monster already exists" });
    return;
  }

  const monster: MonsterRecord = {
    slug: body.slug,
    name: body.name,
    cr: body.cr,
    armorClass: body.armor_class,
    hitPoints: body.hit_points,
    tags: body.tags as string[],
  };
  saveMonster(monster);

  sendJson(res, 201, {
    slug: monster.slug,
    name: monster.name,
    cr: monster.cr,
    armor_class: monster.armorClass,
    hit_points: monster.hitPoints,
  });
}

export function handleGetMonster(res: ServerResponse, slug: string): void {
  const monster = getMonster(slug);
  if (!monster) {
    sendJson(res, 404, { error: "monster not found" });
    return;
  }

  sendJson(res, 200, {
    slug: monster.slug,
    name: monster.name,
    cr: monster.cr,
    armor_class: monster.armorClass,
    hit_points: monster.hitPoints,
    tags: monster.tags,
  });
}

interface ItemRecord {
  slug: string;
  name: string;
  type: string;
  rarity: string;
  costGp: number;
}

function hasItem(slug: string): boolean {
  const row = db.prepare("SELECT 1 FROM items WHERE slug = ?").get(slug);
  return row !== undefined;
}

function getItem(slug: string): ItemRecord | undefined {
  const row = db.prepare("SELECT slug, name, type, rarity, cost_gp FROM items WHERE slug = ?").get(slug) as
    | { slug: string; name: string; type: string; rarity: string; cost_gp: number }
    | undefined;
  if (!row) return undefined;
  return { slug: row.slug, name: row.name, type: row.type, rarity: row.rarity, costGp: row.cost_gp };
}

function saveItem(item: ItemRecord): void {
  db.prepare("INSERT INTO items (slug, name, type, rarity, cost_gp) VALUES (?, ?, ?, ?, ?)").run(
    item.slug,
    item.name,
    item.type,
    item.rarity,
    item.costGp,
  );
}

export function handleCreateItem(res: ServerResponse, body: unknown): void {
  if (
    !isPlainObject(body) ||
    typeof body.slug !== "string" ||
    typeof body.name !== "string" ||
    typeof body.type !== "string" ||
    typeof body.rarity !== "string" ||
    !isValidInt(body.cost_gp, 0, Number.MAX_SAFE_INTEGER)
  ) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  if (!SLUG_RE.test(body.slug)) {
    sendJson(res, 400, { error: "invalid slug" });
    return;
  }

  if (hasItem(body.slug)) {
    sendJson(res, 409, { error: "item already exists" });
    return;
  }

  const item: ItemRecord = {
    slug: body.slug,
    name: body.name,
    type: body.type,
    rarity: body.rarity,
    costGp: body.cost_gp,
  };
  saveItem(item);

  sendJson(res, 201, {
    slug: item.slug,
    name: item.name,
    type: item.type,
    rarity: item.rarity,
    cost_gp: item.costGp,
  });
}

export function handleGetItem(res: ServerResponse, slug: string): void {
  const item = getItem(slug);
  if (!item) {
    sendJson(res, 404, { error: "item not found" });
    return;
  }

  sendJson(res, 200, {
    slug: item.slug,
    name: item.name,
    type: item.type,
    rarity: item.rarity,
    cost_gp: item.costGp,
  });
}
