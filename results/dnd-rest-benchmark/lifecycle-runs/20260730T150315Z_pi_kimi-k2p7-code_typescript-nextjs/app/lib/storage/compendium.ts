/**
 * Compendium repository for monsters and items.
 */

import { getDb } from "./core.js";
import type { CreateItemInput, CreateMonsterInput, Item, Monster } from "../types.js";

export function createMonster(input: CreateMonsterInput): Monster | null {
  const database = getDb();
  database.exec("BEGIN IMMEDIATE;");
  try {
    database
      .prepare(
        "INSERT INTO monsters (slug, name, cr, armor_class, hit_points) VALUES (?, ?, ?, ?, ?)"
      )
      .run(input.slug, input.name, input.cr, input.armor_class, input.hit_points);
    const tagStmt = database.prepare(
      "INSERT INTO monster_tags (monster_slug, tag) VALUES (?, ?)"
    );
    for (const tag of input.tags) {
      tagStmt.run(input.slug, tag);
    }
    database.exec("COMMIT;");
    return {
      slug: input.slug,
      name: input.name,
      cr: input.cr,
      armor_class: input.armor_class,
      hit_points: input.hit_points,
      tags: input.tags,
    };
  } catch {
    database.exec("ROLLBACK;");
    return null;
  }
}

export function getMonster(slug: string): Monster | null {
  const database = getDb();
  const row = database
    .prepare(
      "SELECT slug, name, cr, armor_class, hit_points FROM monsters WHERE slug = ?"
    )
    .get(slug) as
    | { slug: string; name: string; cr: string; armor_class: number; hit_points: number }
    | undefined;
  if (!row) return null;

  const tagRows = database
    .prepare("SELECT tag FROM monster_tags WHERE monster_slug = ? ORDER BY id")
    .all(slug) as Array<{ tag: string }>;

  return {
    ...row,
    tags: tagRows.map((r) => r.tag),
  };
}

export function createItem(input: CreateItemInput): Item | null {
  const database = getDb();
  try {
    database
      .prepare(
        "INSERT INTO items (slug, name, type, rarity, cost_gp) VALUES (?, ?, ?, ?, ?)"
      )
      .run(input.slug, input.name, input.type, input.rarity, input.cost_gp);
    return { ...input };
  } catch {
    return null;
  }
}

export function getItem(slug: string): Item | null {
  const database = getDb();
  const row = database
    .prepare(
      "SELECT slug, name, type, rarity, cost_gp FROM items WHERE slug = ?"
    )
    .get(slug) as
    | { slug: string; name: string; type: string; rarity: string; cost_gp: number }
    | undefined;
  return row || null;
}
