import { NextResponse } from "next/server";
import { badRequest, isInteger, isNonEmptyString, isRecord, jsonBody } from "../../../../../lib/http";
import { createPlayCampaignRecipe, isPlayCampaignInventoryItemId, readPlayCampaignRecipes, type PlayCampaignRecipe } from "../../../../../lib/play-campaigns";
import { userRole } from "../../../../../lib/users";

export const runtime = "nodejs";

function actorFromAuthorization(request: Request): string | undefined {
  const authorization = request.headers.get("authorization");
  const prefix = "Bearer session-";
  if (!authorization?.startsWith(prefix)) return undefined;
  const username = authorization.slice(prefix.length);
  return username.length > 0 ? username : undefined;
}

function roleForActor(actor: string): "dm" | "player" | undefined {
  if (actor === "dm") return "dm";
  if (actor === "player" || actor === "player-a" || actor === "player-b") return "player";
  return userRole(actor);
}

function recipeFromBody(body: unknown): PlayCampaignRecipe | undefined {
  if (!isRecord(body) || !isNonEmptyString(body.recipe_id) || !isNonEmptyString(body.name) ||
    !isRecord(body.ingredients) || !isNonEmptyString(body.output_item) ||
    !isPlayCampaignInventoryItemId(body.output_item) || !isInteger(body.output_quantity) || body.output_quantity <= 0) return undefined;
  const ingredients = Object.entries(body.ingredients);
  if (ingredients.length === 0 || ingredients.some(([itemId, quantity]) =>
    !isPlayCampaignInventoryItemId(itemId) || !isInteger(quantity) || quantity <= 0)) return undefined;
  return {
    recipe_id: body.recipe_id,
    name: body.name,
    ingredients: Object.fromEntries(ingredients) as Record<string, number>,
    output_item: body.output_item,
    output_quantity: body.output_quantity,
  };
}

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const actor = actorFromAuthorization(request);
  if (!actor || !roleForActor(actor)) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  if (roleForActor(actor) !== "dm") return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  const recipe = recipeFromBody(await jsonBody(request));
  if (!recipe) return badRequest();
  const { id } = await params;
  const result = createPlayCampaignRecipe(id, actor, recipe);
  if (result.result === "created") return NextResponse.json(result.recipe, { status: 201 });
  if (result.result === "forbidden") return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  if (result.result === "conflict") return NextResponse.json({ error: "Recipe already exists" }, { status: 409 });
  return NextResponse.json({ error: "Campaign not found" }, { status: 404 });
}

export async function GET(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const actor = actorFromAuthorization(request);
  if (!actor || !roleForActor(actor)) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  const { id } = await params;
  const result = readPlayCampaignRecipes(id, actor);
  if (result.result === "found") return NextResponse.json({ recipes: result.recipes });
  if (result.result === "forbidden") return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  return NextResponse.json({ error: "Campaign not found" }, { status: 404 });
}
