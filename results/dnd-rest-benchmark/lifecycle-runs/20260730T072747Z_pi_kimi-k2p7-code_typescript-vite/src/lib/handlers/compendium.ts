import type { ServerResponse } from 'node:http';
import { sendError, sendJson } from '../http.js';
import {
  createItem,
  createMonster,
  getItem,
  getMonster,
  itemExists,
  monsterExists,
} from '../db.js';
import { isNonEmptyString, isPositiveInteger, isStringArray } from '../validation.js';
import type { Item, Monster } from '../types.js';

export function handleGetMonster(pathname: string, res: ServerResponse): boolean {
  const match = pathname.match(/^\/v1\/compendium\/monsters\/(.+)$/);
  if (!match) return false;
  const slug = match[1];
  const monster = getMonster(slug);
  if (!monster) {
    sendError(res, 404, 'monster not found');
    return true;
  }
  sendJson(res, 200, monster);
  return true;
}

export function handleGetItem(pathname: string, res: ServerResponse): boolean {
  const match = pathname.match(/^\/v1\/compendium\/items\/(.+)$/);
  if (!match) return false;
  const slug = match[1];
  const item = getItem(slug);
  if (!item) {
    sendError(res, 404, 'item not found');
    return true;
  }
  sendJson(res, 200, item);
  return true;
}

export function handleCreateMonster(body: unknown, res: ServerResponse): boolean {
  const b = body as any;
  if (
    !b ||
    !isNonEmptyString(b.slug) ||
    !isNonEmptyString(b.name) ||
    !isNonEmptyString(b.cr) ||
    !isPositiveInteger(b.armor_class) ||
    !isPositiveInteger(b.hit_points) ||
    !isStringArray(b.tags)
  ) {
    sendError(res, 400, 'invalid request');
    return true;
  }
  if (monsterExists(b.slug)) {
    sendError(res, 409, 'monster already exists');
    return true;
  }
  const monster: Monster = {
    slug: b.slug,
    name: b.name,
    cr: b.cr,
    armor_class: b.armor_class,
    hit_points: b.hit_points,
    tags: b.tags,
  };
  createMonster(monster);
  sendJson(res, 201, {
    slug: monster.slug,
    name: monster.name,
    cr: monster.cr,
    armor_class: monster.armor_class,
    hit_points: monster.hit_points,
  });
  return true;
}

export function handleCreateItem(body: unknown, res: ServerResponse): boolean {
  const b = body as any;
  if (
    !b ||
    !isNonEmptyString(b.slug) ||
    !isNonEmptyString(b.name) ||
    !isNonEmptyString(b.type) ||
    !isNonEmptyString(b.rarity) ||
    !isPositiveInteger(b.cost_gp)
  ) {
    sendError(res, 400, 'invalid request');
    return true;
  }
  if (itemExists(b.slug)) {
    sendError(res, 409, 'item already exists');
    return true;
  }
  const item: Item = {
    slug: b.slug,
    name: b.name,
    type: b.type,
    rarity: b.rarity,
    cost_gp: b.cost_gp,
  };
  createItem(item);
  sendJson(res, 201, item);
  return true;
}
