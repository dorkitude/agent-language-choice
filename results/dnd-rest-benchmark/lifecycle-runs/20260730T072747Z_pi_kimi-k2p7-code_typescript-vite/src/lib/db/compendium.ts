// Compendium reference data: monsters and items.

import { db } from './connection.js';
import type { Item, Monster } from '../types.js';

export function createMonster(monster: Monster): void {
  db.prepare('INSERT INTO monsters (slug, name, cr, armor_class, hit_points, tags) VALUES (?, ?, ?, ?, ?, ?)').run(
    monster.slug,
    monster.name,
    monster.cr,
    monster.armor_class,
    monster.hit_points,
    JSON.stringify(monster.tags),
  );
}

export function getMonster(slug: string): Monster | undefined {
  const row = db.prepare('SELECT slug, name, cr, armor_class, hit_points, tags FROM monsters WHERE slug = ?').get(slug) as
    | { slug: string; name: string; cr: string; armor_class: number; hit_points: number; tags: string }
    | undefined;
  if (!row) return undefined;
  return { ...row, tags: JSON.parse(row.tags) as string[] };
}

export function monsterExists(slug: string): boolean {
  const row = db.prepare('SELECT 1 FROM monsters WHERE slug = ?').get(slug) as { '1': number } | undefined;
  return row !== undefined;
}

export function createItem(item: Item): void {
  db.prepare('INSERT INTO items (slug, name, type, rarity, cost_gp) VALUES (?, ?, ?, ?, ?)').run(
    item.slug,
    item.name,
    item.type,
    item.rarity,
    item.cost_gp,
  );
}

export function getItem(slug: string): Item | undefined {
  const row = db.prepare('SELECT slug, name, type, rarity, cost_gp FROM items WHERE slug = ?').get(slug) as
    | { slug: string; name: string; type: string; rarity: string; cost_gp: number }
    | undefined;
  if (!row) return undefined;
  return row;
}

export function itemExists(slug: string): boolean {
  const row = db.prepare('SELECT 1 FROM items WHERE slug = ?').get(slug) as { '1': number } | undefined;
  return row !== undefined;
}
