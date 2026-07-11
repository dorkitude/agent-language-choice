import { getDb } from "./db.js";

export interface Monster {
  slug: string;
  name: string;
  cr: string;
  armor_class: number;
  hit_points: number;
  tags: string[];
}

export interface Item {
  slug: string;
  name: string;
  type: string;
  rarity: string;
  cost_gp: number;
}

export function createMonster(
  input: Record<string, unknown>
): Omit<Monster, "tags"> {
  const slug = validateSlug(input.slug);
  const name = validateName(input.name);
  const cr = validateString(input.cr, "cr");
  const armor_class = validateInteger(input.armor_class, "armor_class");
  const hit_points = validateInteger(input.hit_points, "hit_points");
  const tags = validateStringArray(input.tags, "tags");

  const db = getDb();
  const existing = db
    .prepare("SELECT slug FROM monsters WHERE slug = ?")
    .get(slug);
  if (existing) {
    throw new Error("monster slug already exists");
  }

  db.prepare(
    `
    INSERT INTO monsters (slug, name, cr, armor_class, hit_points, tags_json)
    VALUES (?, ?, ?, ?, ?, ?)
    `
  ).run(slug, name, cr, armor_class, hit_points, JSON.stringify(tags));

  return { slug, name, cr, armor_class, hit_points };
}

export function getMonster(slug: string): Monster | undefined {
  const db = getDb();
  const row = db
    .prepare(
      `
      SELECT slug, name, cr, armor_class, hit_points, tags_json
      FROM monsters WHERE slug = ?
      `
    )
    .get(slug) as Record<string, unknown> | undefined;
  if (!row) return undefined;
  return {
    slug: String(row.slug),
    name: String(row.name),
    cr: String(row.cr),
    armor_class: Number(row.armor_class),
    hit_points: Number(row.hit_points),
    tags: JSON.parse(String(row.tags_json)),
  };
}

export function createItem(input: Record<string, unknown>): Item {
  const slug = validateSlug(input.slug);
  const name = validateName(input.name);
  const type = validateString(input.type, "type");
  const rarity = validateString(input.rarity, "rarity");
  const cost_gp = validateInteger(input.cost_gp, "cost_gp");

  const db = getDb();
  const existing = db.prepare("SELECT slug FROM items WHERE slug = ?").get(slug);
  if (existing) {
    throw new Error("item slug already exists");
  }

  db.prepare(
    `
    INSERT INTO items (slug, name, type, rarity, cost_gp)
    VALUES (?, ?, ?, ?, ?)
    `
  ).run(slug, name, type, rarity, cost_gp);

  return { slug, name, type, rarity, cost_gp };
}

export function getItem(slug: string): Item | undefined {
  const db = getDb();
  const row = db
    .prepare(
      `
      SELECT slug, name, type, rarity, cost_gp
      FROM items WHERE slug = ?
      `
    )
    .get(slug) as Record<string, unknown> | undefined;
  if (!row) return undefined;
  return {
    slug: String(row.slug),
    name: String(row.name),
    type: String(row.type),
    rarity: String(row.rarity),
    cost_gp: Number(row.cost_gp),
  };
}

function validateSlug(value: unknown): string {
  if (typeof value !== "string" || value.length === 0) {
    throw new Error("slug must be a non-empty string");
  }
  return value;
}

function validateName(value: unknown): string {
  if (typeof value !== "string" || value.length === 0) {
    throw new Error("name must be a non-empty string");
  }
  return value;
}

function validateString(value: unknown, field: string): string {
  if (typeof value !== "string" || value.length === 0) {
    throw new Error(`${field} must be a non-empty string`);
  }
  return value;
}

function validateInteger(value: unknown, field: string): number {
  if (typeof value !== "number" || !Number.isInteger(value)) {
    throw new Error(`${field} must be an integer`);
  }
  return value;
}

function validateStringArray(value: unknown, field: string): string[] {
  if (!Array.isArray(value)) {
    throw new Error(`${field} must be an array`);
  }
  for (const item of value) {
    if (typeof item !== "string") {
      throw new Error(`${field} must be an array of strings`);
    }
  }
  return value;
}
