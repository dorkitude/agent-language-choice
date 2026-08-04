/**
 * Compendium: the write-once reference tables of monsters and items, keyed by
 * slug. Entries are created and read back verbatim; nothing here updates or
 * deletes, so a slug that exists is a 409 on create.
 */
import { database } from "./db";
import { isNonEmptyString } from "./validation";

export type Monster = {
  slug: string;
  name: string;
  cr: string | number;
  armor_class: number;
  hit_points: number;
  tags: string[];
};

export type Item = {
  slug: string;
  name: string;
  type: string;
  rarity: string;
  cost_gp: number;
};

/**
 * Challenge rating is a fractional label such as "1/4" for weak monsters and a
 * plain number for the rest, so both JSON types are accepted. The original
 * value is stored as JSON and echoed back unchanged — "1/2" and 0.5 do not
 * normalize to each other on the way out.
 */
export function isValidCr(value: unknown): value is string | number {
  if (typeof value === "number") return Number.isFinite(value) && value >= 0;
  return typeof value === "string" && /^\d+(\/\d+)?$/.test(value.trim());
}

/** Tags are optional; when present they must be a list of non-empty strings. */
export function parseTags(value: unknown): string[] | undefined {
  if (value === undefined || value === null) return [];
  if (!Array.isArray(value)) return undefined;
  if (!value.every(isNonEmptyString)) return undefined;
  return value as string[];
}

export function getMonster(slug: string): Monster | undefined {
  const row = database()
    .prepare(
      `SELECT slug, name, cr_json, armor_class, hit_points, tags_json
       FROM monsters WHERE slug = ?`,
    )
    .get(slug) as Record<string, unknown> | undefined;
  if (!row) return undefined;
  return {
    slug: row.slug as string,
    name: row.name as string,
    cr: JSON.parse(row.cr_json as string) as string | number,
    armor_class: Number(row.armor_class),
    hit_points: Number(row.hit_points),
    tags: JSON.parse(row.tags_json as string) as string[],
  };
}

export function insertMonster(monster: Monster): void {
  database()
    .prepare(
      `INSERT INTO monsters (slug, name, cr_json, armor_class, hit_points, tags_json)
       VALUES (?, ?, ?, ?, ?, ?)`,
    )
    .run(
      monster.slug,
      monster.name,
      JSON.stringify(monster.cr),
      monster.armor_class,
      monster.hit_points,
      JSON.stringify(monster.tags),
    );
}

export function getItem(slug: string): Item | undefined {
  const row = database()
    .prepare("SELECT slug, name, type, rarity, cost_gp FROM items WHERE slug = ?")
    .get(slug) as Record<string, unknown> | undefined;
  if (!row) return undefined;
  return {
    slug: row.slug as string,
    name: row.name as string,
    type: row.type as string,
    rarity: row.rarity as string,
    cost_gp: Number(row.cost_gp),
  };
}

export function insertItem(item: Item): void {
  database()
    .prepare(
      "INSERT INTO items (slug, name, type, rarity, cost_gp) VALUES (?, ?, ?, ?, ?)",
    )
    .run(item.slug, item.name, item.type, item.rarity, item.cost_gp);
}
