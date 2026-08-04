/** Monster and item compendium: create-and-fetch reference data backed by SQLite directly (no in-memory cache). */

import { getDb } from '../db.ts';
import type { ApiResult, JsonValue } from '../types.ts';
import { isValidIntInRange } from '../validation.ts';

const SLUG_RE = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;

interface MonsterRow {
  slug: string;
  name: string;
  cr: string;
  armor_class: number;
  hit_points: number;
  tags_json: string;
}

function monsterRowToBody(row: MonsterRow): JsonValue {
  return {
    slug: row.slug,
    name: row.name,
    cr: row.cr,
    armor_class: row.armor_class,
    hit_points: row.hit_points,
    tags: JSON.parse(row.tags_json),
  };
}

export function createMonster(body: JsonValue): ApiResult {
  const slug = body.slug;
  if (typeof slug !== 'string' || !SLUG_RE.test(slug)) {
    return { status: 400, body: { error: 'slug must be a lowercase kebab-case string' } };
  }

  const name = body.name;
  if (typeof name !== 'string' || name.length === 0) {
    return { status: 400, body: { error: 'name must be a non-empty string' } };
  }

  const cr = body.cr;
  if (typeof cr !== 'string' || cr.length === 0) {
    return { status: 400, body: { error: 'cr must be a non-empty string' } };
  }

  const armorClass = body.armor_class;
  if (!isValidIntInRange(armorClass, 0, Number.MAX_SAFE_INTEGER)) {
    return { status: 400, body: { error: 'armor_class must be a non-negative integer' } };
  }

  const hitPoints = body.hit_points;
  if (!isValidIntInRange(hitPoints, 0, Number.MAX_SAFE_INTEGER)) {
    return { status: 400, body: { error: 'hit_points must be a non-negative integer' } };
  }

  const tags = body.tags ?? [];
  if (!Array.isArray(tags) || !tags.every((t) => typeof t === 'string')) {
    return { status: 400, body: { error: 'tags must be an array of strings' } };
  }

  const db = getDb();
  const existing = db.prepare('SELECT slug FROM monsters WHERE slug = ?').get(slug);
  if (existing) {
    return { status: 409, body: { error: 'monster slug already exists' } };
  }

  db.prepare(
    'INSERT INTO monsters (slug, name, cr, armor_class, hit_points, tags_json) VALUES (?, ?, ?, ?, ?, ?)',
  ).run(slug, name, cr, armorClass, hitPoints, JSON.stringify(tags));

  return {
    status: 201,
    body: { slug, name, cr, armor_class: armorClass, hit_points: hitPoints },
  };
}

export function getMonster(slug: string): ApiResult {
  const db = getDb();
  const row = db.prepare('SELECT slug, name, cr, armor_class, hit_points, tags_json FROM monsters WHERE slug = ?').get(
    slug,
  ) as MonsterRow | undefined;
  if (!row) {
    return { status: 404, body: { error: 'unknown monster slug' } };
  }
  return { status: 200, body: monsterRowToBody(row) };
}

interface ItemRow {
  slug: string;
  name: string;
  type: string;
  rarity: string;
  cost_gp: number;
}

function itemRowToBody(row: ItemRow): JsonValue {
  return {
    slug: row.slug,
    name: row.name,
    type: row.type,
    rarity: row.rarity,
    cost_gp: row.cost_gp,
  };
}

export function createItem(body: JsonValue): ApiResult {
  const slug = body.slug;
  if (typeof slug !== 'string' || !SLUG_RE.test(slug)) {
    return { status: 400, body: { error: 'slug must be a lowercase kebab-case string' } };
  }

  const name = body.name;
  if (typeof name !== 'string' || name.length === 0) {
    return { status: 400, body: { error: 'name must be a non-empty string' } };
  }

  const type = body.type;
  if (typeof type !== 'string' || type.length === 0) {
    return { status: 400, body: { error: 'type must be a non-empty string' } };
  }

  const rarity = body.rarity;
  if (typeof rarity !== 'string' || rarity.length === 0) {
    return { status: 400, body: { error: 'rarity must be a non-empty string' } };
  }

  const costGp = body.cost_gp;
  if (typeof costGp !== 'number' || !Number.isFinite(costGp) || costGp < 0) {
    return { status: 400, body: { error: 'cost_gp must be a non-negative number' } };
  }

  const db = getDb();
  const existing = db.prepare('SELECT slug FROM items WHERE slug = ?').get(slug);
  if (existing) {
    return { status: 409, body: { error: 'item slug already exists' } };
  }

  db.prepare('INSERT INTO items (slug, name, type, rarity, cost_gp) VALUES (?, ?, ?, ?, ?)').run(
    slug,
    name,
    type,
    rarity,
    costGp,
  );

  return {
    status: 201,
    body: { slug, name, type, rarity, cost_gp: costGp },
  };
}

export function getItem(slug: string): ApiResult {
  const db = getDb();
  const row = db.prepare('SELECT slug, name, type, rarity, cost_gp FROM items WHERE slug = ?').get(
    slug,
  ) as ItemRow | undefined;
  if (!row) {
    return { status: 404, body: { error: 'unknown item slug' } };
  }
  return { status: 200, body: itemRowToBody(row) };
}
