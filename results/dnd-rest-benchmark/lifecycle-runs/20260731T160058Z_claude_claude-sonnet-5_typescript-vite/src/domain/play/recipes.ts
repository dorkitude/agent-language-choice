/**
 * DM-defined crafting recipes with deterministic ingredient costs, backed by
 * the public campaign inventory item catalog. See shared.ts for the
 * ownership model and inventory.ts for the item catalog and stacks.
 */

import { getDb } from '../../db.ts';
import type { ApiResult, JsonValue } from '../../types.ts';
import { isValidIntInRange } from '../../validation.ts';
import { VALID_ITEM_IDS } from './inventory.ts';
import {
  authenticate,
  isActor,
  isApiResult,
  findCampaign,
  requireParticipant,
  resolveCharacterOwner,
} from './shared.ts';

type RecipeRow = {
  recipe_id: string;
  name: string;
  ingredients_json: string;
  output_item: string;
  output_quantity: number;
};

function recipeBody(row: RecipeRow): JsonValue {
  return {
    recipe_id: row.recipe_id,
    name: row.name,
    ingredients: JSON.parse(row.ingredients_json),
    output_item: row.output_item,
    output_quantity: row.output_quantity,
  } as JsonValue;
}

function parseIngredients(value: unknown): Record<string, number> | ApiResult {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    return { status: 400, body: { error: 'ingredients must be a non-empty object' } };
  }
  const entries = Object.entries(value as Record<string, unknown>);
  if (entries.length === 0) {
    return { status: 400, body: { error: 'ingredients must be a non-empty object' } };
  }
  const ingredients: Record<string, number> = {};
  for (const [itemId, quantity] of entries) {
    if (!VALID_ITEM_IDS.has(itemId)) {
      return { status: 400, body: { error: 'ingredients keys must be valid catalog item ids' } };
    }
    if (!isValidIntInRange(quantity, 1, Number.MAX_SAFE_INTEGER)) {
      return { status: 400, body: { error: 'ingredients values must be positive integers' } };
    }
    ingredients[itemId] = quantity as number;
  }
  return ingredients;
}

function parseRecipeFields(
  body: JsonValue,
): { name: string; ingredients: Record<string, number>; outputItem: string; outputQuantity: number } | ApiResult {
  const name = body.name;
  if (typeof name !== 'string' || name.length === 0) {
    return { status: 400, body: { error: 'name must be a non-empty string' } };
  }

  const ingredients = parseIngredients(body.ingredients);
  if (isApiResult(ingredients)) return ingredients;

  const outputItem = body.output_item;
  if (typeof outputItem !== 'string' || !VALID_ITEM_IDS.has(outputItem)) {
    return { status: 400, body: { error: 'output_item must be a valid catalog item id' } };
  }

  if (!isValidIntInRange(body.output_quantity, 1, Number.MAX_SAFE_INTEGER)) {
    return { status: 400, body: { error: 'output_quantity must be a positive integer' } };
  }

  return { name, ingredients, outputItem, outputQuantity: body.output_quantity as number };
}

function nextRecipeSequence(db: ReturnType<typeof getDb>, campaignId: string): number {
  const row = db
    .prepare('SELECT COALESCE(MAX(sequence), 0) AS max_sequence FROM play_campaign_recipes WHERE campaign_id = ?')
    .get(campaignId) as { max_sequence: number };
  return row.max_sequence + 1;
}

function findRecipe(db: ReturnType<typeof getDb>, campaignId: string, recipeId: string): RecipeRow | ApiResult {
  const row = db
    .prepare(
      'SELECT recipe_id, name, ingredients_json, output_item, output_quantity FROM play_campaign_recipes WHERE campaign_id = ? AND recipe_id = ?',
    )
    .get(campaignId, recipeId) as RecipeRow | undefined;
  return row ?? { status: 404, body: { error: 'recipe not found' } };
}

export function createRecipe(authHeader: string | undefined, campaignId: string, body: JsonValue): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  if (campaign.owner !== actor.username) {
    return { status: 403, body: { error: 'only the campaign dm may create recipes' } };
  }

  const recipeId = body.recipe_id;
  if (typeof recipeId !== 'string' || recipeId.length === 0) {
    return { status: 400, body: { error: 'recipe_id must be a non-empty string' } };
  }

  const parsed = parseRecipeFields(body);
  if (isApiResult(parsed)) return parsed;

  const existing = db
    .prepare('SELECT recipe_id FROM play_campaign_recipes WHERE campaign_id = ? AND recipe_id = ?')
    .get(campaignId, recipeId);
  if (existing) {
    return { status: 409, body: { error: 'recipe_id already exists in this campaign' } };
  }

  const sequence = nextRecipeSequence(db, campaignId);
  const ingredientsJson = JSON.stringify(parsed.ingredients);
  db.prepare(
    'INSERT INTO play_campaign_recipes (campaign_id, sequence, recipe_id, name, ingredients_json, output_item, output_quantity) VALUES (?, ?, ?, ?, ?, ?, ?)',
  ).run(campaignId, sequence, recipeId, parsed.name, ingredientsJson, parsed.outputItem, parsed.outputQuantity);

  return {
    status: 201,
    body: recipeBody({
      recipe_id: recipeId,
      name: parsed.name,
      ingredients_json: ingredientsJson,
      output_item: parsed.outputItem,
      output_quantity: parsed.outputQuantity,
    }),
  };
}

export function listRecipes(authHeader: string | undefined, campaignId: string): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  const forbidden = requireParticipant(db, campaign, actor, 'not a campaign member');
  if (forbidden) return forbidden;

  const rows = db
    .prepare(
      'SELECT recipe_id, name, ingredients_json, output_item, output_quantity FROM play_campaign_recipes WHERE campaign_id = ? ORDER BY sequence ASC',
    )
    .all(campaignId) as RecipeRow[];

  return { status: 200, body: { recipes: rows.map(recipeBody) } };
}

export function craftRecipe(
  authHeader: string | undefined,
  campaignId: string,
  recipeId: string,
  body: JsonValue,
): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  const recipe = findRecipe(db, campaignId, recipeId);
  if (isApiResult(recipe)) return recipe;

  const characterId = body.character_id;
  if (typeof characterId !== 'string' || characterId.length === 0) {
    return { status: 400, body: { error: 'character_id must be a non-empty string' } };
  }

  const owner = resolveCharacterOwner(db, campaignId, characterId);
  if (!owner) {
    return { status: 404, body: { error: 'character not found' } };
  }
  if (owner !== actor.username) {
    return { status: 403, body: { error: 'only the character owner may craft' } };
  }

  const ingredients = JSON.parse(recipe.ingredients_json) as Record<string, number>;
  const held = new Map<string, number>();
  for (const itemId of Object.keys(ingredients)) {
    const stack = db
      .prepare('SELECT quantity FROM play_campaign_inventory_stacks WHERE campaign_id = ? AND character_id = ? AND item_id = ?')
      .get(campaignId, characterId, itemId) as { quantity: number } | undefined;
    const quantity = stack?.quantity ?? 0;
    held.set(itemId, quantity);
    if (quantity < ingredients[itemId]) {
      return { status: 409, body: { error: 'insufficient ingredients' } };
    }
  }

  for (const [itemId, requiredQuantity] of Object.entries(ingredients)) {
    const remaining = (held.get(itemId) as number) - requiredQuantity;
    if (remaining === 0) {
      db.prepare('DELETE FROM play_campaign_inventory_stacks WHERE campaign_id = ? AND character_id = ? AND item_id = ?').run(
        campaignId,
        characterId,
        itemId,
      );
    } else {
      db.prepare(
        'UPDATE play_campaign_inventory_stacks SET quantity = ? WHERE campaign_id = ? AND character_id = ? AND item_id = ?',
      ).run(remaining, campaignId, characterId, itemId);
    }
  }

  const existingOutput = db
    .prepare('SELECT quantity FROM play_campaign_inventory_stacks WHERE campaign_id = ? AND character_id = ? AND item_id = ?')
    .get(campaignId, characterId, recipe.output_item) as { quantity: number } | undefined;
  const totalOutput = (existingOutput?.quantity ?? 0) + recipe.output_quantity;
  if (existingOutput) {
    db.prepare(
      'UPDATE play_campaign_inventory_stacks SET quantity = ? WHERE campaign_id = ? AND character_id = ? AND item_id = ?',
    ).run(totalOutput, campaignId, characterId, recipe.output_item);
  } else {
    db.prepare(
      'INSERT INTO play_campaign_inventory_stacks (campaign_id, character_id, item_id, quantity) VALUES (?, ?, ?, ?)',
    ).run(campaignId, characterId, recipe.output_item, totalOutput);
  }

  return {
    status: 201,
    body: {
      character_id: characterId,
      recipe_id: recipeId,
      output_item: recipe.output_item,
      output_quantity: recipe.output_quantity,
    },
  };
}
