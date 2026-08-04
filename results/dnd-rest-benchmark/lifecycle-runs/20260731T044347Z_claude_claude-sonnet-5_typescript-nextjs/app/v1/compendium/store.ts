import { getDb } from "../db.js";

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

export function hasMonster(slug: string): boolean {
  const row = getDb().prepare("SELECT slug FROM monsters WHERE slug = ?").get(slug);
  return row !== undefined;
}

export function getMonster(slug: string): Monster | undefined {
  const row = getDb().prepare("SELECT data FROM monsters WHERE slug = ?").get(slug) as
    | { data: string }
    | undefined;
  if (!row) return undefined;
  return JSON.parse(row.data) as Monster;
}

export function createMonster(monster: Monster): Monster {
  getDb()
    .prepare("INSERT INTO monsters (slug, data) VALUES (?, ?)")
    .run(monster.slug, JSON.stringify(monster));
  return monster;
}

export function hasItem(slug: string): boolean {
  const row = getDb().prepare("SELECT slug FROM items WHERE slug = ?").get(slug);
  return row !== undefined;
}

export function getItem(slug: string): Item | undefined {
  const row = getDb().prepare("SELECT data FROM items WHERE slug = ?").get(slug) as
    | { data: string }
    | undefined;
  if (!row) return undefined;
  return JSON.parse(row.data) as Item;
}

export function createItem(item: Item): Item {
  getDb()
    .prepare("INSERT INTO items (slug, data) VALUES (?, ?)")
    .run(item.slug, JSON.stringify(item));
  return item;
}
