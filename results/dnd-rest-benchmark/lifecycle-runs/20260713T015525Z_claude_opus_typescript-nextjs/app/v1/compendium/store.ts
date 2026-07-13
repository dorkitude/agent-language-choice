import { getDb } from "../db";

export type Monster = {
  slug: string;
  name: string;
  cr: string;
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

export const SLUG_RE = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;

export function getMonster(slug: string): Monster | undefined {
  const row = getDb()
    .prepare(
      "SELECT slug, name, cr, armor_class, hit_points, tags_json FROM monsters WHERE slug = ?"
    )
    .get(slug) as
    | {
        slug: string;
        name: string;
        cr: string;
        armor_class: number;
        hit_points: number;
        tags_json: string;
      }
    | undefined;
  if (!row) return undefined;
  return {
    slug: row.slug,
    name: row.name,
    cr: row.cr,
    armor_class: row.armor_class,
    hit_points: row.hit_points,
    tags: JSON.parse(row.tags_json) as string[],
  };
}

export function hasMonster(slug: string): boolean {
  return getMonster(slug) !== undefined;
}

export function createMonster(m: Monster): void {
  getDb()
    .prepare(
      "INSERT INTO monsters (slug, name, cr, armor_class, hit_points, tags_json) VALUES (?, ?, ?, ?, ?, ?)"
    )
    .run(m.slug, m.name, m.cr, m.armor_class, m.hit_points, JSON.stringify(m.tags));
}

export function getItem(slug: string): Item | undefined {
  const row = getDb()
    .prepare(
      "SELECT slug, name, type, rarity, cost_gp FROM items WHERE slug = ?"
    )
    .get(slug) as Item | undefined;
  return row;
}

export function hasItem(slug: string): boolean {
  return getItem(slug) !== undefined;
}

export function createItem(i: Item): void {
  getDb()
    .prepare(
      "INSERT INTO items (slug, name, type, rarity, cost_gp) VALUES (?, ?, ?, ?, ?)"
    )
    .run(i.slug, i.name, i.type, i.rarity, i.cost_gp);
}
