import { requireSession } from "../../../../auth/session.js";
import { parseJsonBody, requireNonEmptyString } from "../../../../http.js";
import { requireCampaignOwner, requirePlayCampaign } from "../../../http.js";
import {
  createPlayRecipe,
  getPlayMemberForUser,
  hasPlayRecipe,
  listPlayRecipes,
  PlayRecipe,
  VALID_INVENTORY_ITEM_IDS,
} from "../../../store.js";

function serializeRecipe(recipe: PlayRecipe) {
  return {
    recipe_id: recipe.recipe_id,
    name: recipe.name,
    ingredients: recipe.ingredients,
    output_item: recipe.output_item,
    output_quantity: recipe.output_quantity,
  };
}

function parseIngredients(value: unknown): Record<string, number> | Response {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return Response.json({ error: "ingredients must be a non-empty object" }, { status: 400 });
  }

  const entries = Object.entries(value as Record<string, unknown>);
  if (entries.length === 0) {
    return Response.json({ error: "ingredients must be a non-empty object" }, { status: 400 });
  }

  const ingredients: Record<string, number> = {};
  for (const [itemId, quantity] of entries) {
    if (!(VALID_INVENTORY_ITEM_IDS as readonly string[]).includes(itemId)) {
      return Response.json(
        { error: `ingredients key ${itemId} must be a known catalog item` },
        { status: 400 },
      );
    }
    if (typeof quantity !== "number" || !Number.isInteger(quantity) || quantity < 1) {
      return Response.json(
        { error: `ingredients quantity for ${itemId} must be a positive integer` },
        { status: 400 },
      );
    }
    ingredients[itemId] = quantity;
  }

  return ingredients;
}

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id: campaignId } = await params;

  const session = requireSession(request);
  if (!session.ok) return session.response;

  const campaign = requirePlayCampaign(campaignId);
  if (campaign instanceof Response) return campaign;

  const ownerCheck = requireCampaignOwner(
    campaign,
    session.user.username,
    "only the campaign dm may create recipes",
  );
  if (ownerCheck) return ownerCheck;

  const parsed = await parseJsonBody(request);
  if (!parsed.ok) return parsed.response;
  const body = parsed.body as {
    recipe_id?: unknown;
    name?: unknown;
    ingredients?: unknown;
    output_item?: unknown;
    output_quantity?: unknown;
  };

  const validRecipeId = requireNonEmptyString(body.recipe_id, "recipe_id");
  if (validRecipeId instanceof Response) return validRecipeId;

  const validName = requireNonEmptyString(body.name, "name");
  if (validName instanceof Response) return validName;

  const ingredients = parseIngredients(body.ingredients);
  if (ingredients instanceof Response) return ingredients;

  const outputItem = body.output_item;
  if (
    typeof outputItem !== "string" ||
    !(VALID_INVENTORY_ITEM_IDS as readonly string[]).includes(outputItem)
  ) {
    return Response.json({ error: "output_item must be a known catalog item" }, { status: 400 });
  }

  const outputQuantity = body.output_quantity;
  if (
    typeof outputQuantity !== "number" ||
    !Number.isInteger(outputQuantity) ||
    outputQuantity < 1
  ) {
    return Response.json(
      { error: "output_quantity must be a positive integer" },
      { status: 400 },
    );
  }

  if (hasPlayRecipe(campaignId, validRecipeId)) {
    return Response.json(
      { error: `recipe ${validRecipeId} already exists in campaign ${campaignId}` },
      { status: 409 },
    );
  }

  const recipe: PlayRecipe = {
    campaign_id: campaignId,
    recipe_id: validRecipeId,
    name: validName,
    ingredients,
    output_item: outputItem,
    output_quantity: outputQuantity,
  };
  createPlayRecipe(recipe);

  return Response.json(serializeRecipe(recipe), { status: 201 });
}

export async function GET(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id: campaignId } = await params;

  const session = requireSession(request);
  if (!session.ok) return session.response;

  const campaign = requirePlayCampaign(campaignId);
  if (campaign instanceof Response) return campaign;

  const username = session.user.username;
  const isDm = username === campaign.owner;
  const member = isDm ? undefined : getPlayMemberForUser(campaignId, username);
  const isMember = isDm || member !== undefined;
  if (!isMember) {
    return Response.json(
      { error: `${username} is not a member of campaign ${campaignId}` },
      { status: 403 },
    );
  }

  const recipes = listPlayRecipes(campaignId);

  return Response.json({ recipes: recipes.map(serializeRecipe) }, { status: 200 });
}
