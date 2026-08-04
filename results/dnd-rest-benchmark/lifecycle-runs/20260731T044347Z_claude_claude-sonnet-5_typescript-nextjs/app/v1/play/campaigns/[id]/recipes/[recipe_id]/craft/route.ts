import { requireSession } from "../../../../../../auth/session.js";
import { parseJsonBody, requireNonEmptyString } from "../../../../../../http.js";
import { requirePlayCampaign } from "../../../../../http.js";
import {
  getPlayMemberByCharacterId,
  getPlayRecipe,
  updatePlayMember,
} from "../../../../../store.js";

export async function POST(
  request: Request,
  { params }: { params: Promise<{ id: string; recipe_id: string }> },
) {
  const { id: campaignId, recipe_id: recipeId } = await params;

  const session = requireSession(request);
  if (!session.ok) return session.response;

  const campaign = requirePlayCampaign(campaignId);
  if (campaign instanceof Response) return campaign;

  const recipe = getPlayRecipe(campaignId, recipeId);
  if (!recipe) {
    return Response.json(
      { error: `recipe ${recipeId} not found in campaign ${campaignId}` },
      { status: 404 },
    );
  }

  const parsed = await parseJsonBody(request);
  if (!parsed.ok) return parsed.response;
  const body = parsed.body as { character_id?: unknown };

  const validCharacterId = requireNonEmptyString(body.character_id, "character_id");
  if (validCharacterId instanceof Response) return validCharacterId;

  const username = session.user.username;
  if (username === campaign.owner) {
    return Response.json({ error: "the dm may not craft recipes" }, { status: 403 });
  }

  const member = getPlayMemberByCharacterId(campaignId, validCharacterId);
  if (!member) {
    return Response.json(
      { error: `character ${validCharacterId} not found in campaign ${campaignId}` },
      { status: 404 },
    );
  }

  const currentOwner = member.owner ?? member.username;
  if (username !== currentOwner) {
    return Response.json(
      { error: `only ${currentOwner} may craft for character ${validCharacterId}` },
      { status: 403 },
    );
  }

  const items = [...(member.inventory_items ?? [])];
  for (const [itemId, requiredQuantity] of Object.entries(recipe.ingredients)) {
    const held = items.find((item) => item.item_id === itemId)?.quantity ?? 0;
    if (held < requiredQuantity) {
      return Response.json(
        { error: `character ${validCharacterId} does not have enough ${itemId}` },
        { status: 409 },
      );
    }
  }

  let updatedItems = items;
  for (const [itemId, requiredQuantity] of Object.entries(recipe.ingredients)) {
    const heldQuantity = updatedItems.find((item) => item.item_id === itemId)?.quantity ?? 0;
    const remainingQuantity = heldQuantity - requiredQuantity;
    updatedItems = updatedItems.filter((item) => item.item_id !== itemId);
    if (remainingQuantity > 0) {
      updatedItems.push({ item_id: itemId, quantity: remainingQuantity });
    }
  }

  const existingOutput = updatedItems.find((item) => item.item_id === recipe.output_item);
  if (existingOutput) {
    existingOutput.quantity += recipe.output_quantity;
  } else {
    updatedItems.push({ item_id: recipe.output_item, quantity: recipe.output_quantity });
  }

  updatePlayMember({ ...member, inventory_items: updatedItems });

  return Response.json(
    {
      character_id: validCharacterId,
      recipe_id: recipe.recipe_id,
      output_item: recipe.output_item,
      output_quantity: recipe.output_quantity,
    },
    { status: 201 },
  );
}
