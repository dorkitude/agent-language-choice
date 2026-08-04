import { database } from "./storage";

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

export function createMonster(monster: Monster): boolean {
  try {
    database.prepare(
      "INSERT INTO compendium_monsters (slug, name, cr, armor_class, hit_points, tags_json) VALUES (?, ?, ?, ?, ?, ?)",
    ).run(monster.slug, monster.name, monster.cr, monster.armor_class, monster.hit_points, JSON.stringify(monster.tags));
    return true;
  } catch {
    return false;
  }
}

export function getMonster(slug: string): Monster | undefined {
  const row = database.prepare(
    "SELECT slug, name, cr, armor_class, hit_points, tags_json FROM compendium_monsters WHERE slug = ?",
  ).get(slug) as Omit<Monster, "tags"> & { tags_json: string } | undefined;
  if (!row) return undefined;
  try {
    const tags = JSON.parse(row.tags_json);
    return Array.isArray(tags) && tags.every((tag) => typeof tag === "string")
      ? { slug: row.slug, name: row.name, cr: row.cr, armor_class: row.armor_class, hit_points: row.hit_points, tags }
      : undefined;
  } catch {
    return undefined;
  }
}

export function createItem(item: Item): boolean {
  try {
    database.prepare(
      "INSERT INTO compendium_items (slug, name, type, rarity, cost_gp) VALUES (?, ?, ?, ?, ?)",
    ).run(item.slug, item.name, item.type, item.rarity, item.cost_gp);
    return true;
  } catch {
    return false;
  }
}

export function getItem(slug: string): Item | undefined {
  return database.prepare(
    "SELECT slug, name, type, rarity, cost_gp FROM compendium_items WHERE slug = ?",
  ).get(slug) as Item | undefined;
}
