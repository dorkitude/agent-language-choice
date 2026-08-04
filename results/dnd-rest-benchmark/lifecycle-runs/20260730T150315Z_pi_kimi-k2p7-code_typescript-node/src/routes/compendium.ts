import { ServerResponse } from 'node:http';
import { sendJSON } from '../http-utils.js';
import { createItem, createMonster, getItem, getMonster, itemExists, monsterExists } from '../repository.js';
import { isNonEmptyString, isStringArray } from '../validators.js';
import type { Item, Monster } from '../types.js';

export function handleGetMonster(res: ServerResponse, params: Record<string, string>): void {
  const monster = getMonster(params.slug);
  if (!monster) {
    sendJSON(res, 404, { error: 'not found' });
    return;
  }
  sendJSON(res, 200, monster);
}

export function handleCreateMonster(res: ServerResponse, _params: unknown, body: unknown): void {
  const { slug, name, cr, armor_class, hit_points, tags } = body as Record<string, unknown>;
  if (
    !isNonEmptyString(slug) ||
    typeof name !== 'string' ||
    typeof cr !== 'string' ||
    !Number.isInteger(armor_class) ||
    !Number.isInteger(hit_points)
  ) {
    sendJSON(res, 400, { error: 'invalid input' });
    return;
  }

  const parsedTags = tags === undefined ? [] : isStringArray(tags) ? tags : null;
  if (parsedTags === null) {
    sendJSON(res, 400, { error: 'invalid input' });
    return;
  }

  if (monsterExists(slug)) {
    sendJSON(res, 409, { error: 'slug already exists' });
    return;
  }

  const monster: Monster = {
    slug,
    name,
    cr,
    armor_class: Number(armor_class),
    hit_points: Number(hit_points),
    tags: parsedTags,
  };
  createMonster(monster);
  sendJSON(res, 201, {
    slug: monster.slug,
    name: monster.name,
    cr: monster.cr,
    armor_class: monster.armor_class,
    hit_points: monster.hit_points,
  });
}

export function handleGetItem(res: ServerResponse, params: Record<string, string>): void {
  const item = getItem(params.slug);
  if (!item) {
    sendJSON(res, 404, { error: 'not found' });
    return;
  }
  sendJSON(res, 200, item);
}

export function handleCreateItem(res: ServerResponse, _params: unknown, body: unknown): void {
  const { slug, name, type, rarity, cost_gp } = body as Record<string, unknown>;
  if (
    !isNonEmptyString(slug) ||
    typeof name !== 'string' ||
    typeof type !== 'string' ||
    typeof rarity !== 'string' ||
    !Number.isInteger(cost_gp)
  ) {
    sendJSON(res, 400, { error: 'invalid input' });
    return;
  }

  if (itemExists(slug)) {
    sendJSON(res, 409, { error: 'slug already exists' });
    return;
  }

  const item: Item = {
    slug,
    name,
    type,
    rarity,
    cost_gp: Number(cost_gp),
  };
  createItem(item);
  sendJSON(res, 201, item);
}
