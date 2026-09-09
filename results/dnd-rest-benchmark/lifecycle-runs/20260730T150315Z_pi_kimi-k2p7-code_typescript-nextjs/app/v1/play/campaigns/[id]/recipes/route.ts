import { requireBearerAuth } from "../../../../../lib/auth.js";
import {
  badRequest,
  conflict,
  created,
  forbidden,
  notFound,
  ok,
  parseJsonBody,
} from "../../../../../lib/http.js";
import {
  createRecipe,
  getPlayCampaign,
  getPlayCampaignMembers,
  listRecipes,
} from "../../../../../lib/storage.js";
import { isNonEmptyString } from "../../../../../lib/validate.js";

export const dynamic = "force-dynamic";

export async function POST(
  req: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const auth = requireBearerAuth(req, "dm");
  if (!auth.ok) return auth.response;

  const { id } = await params;

  const campaign = getPlayCampaign(id);
  if (!campaign) {
    return notFound();
  }

  if (campaign.owner !== auth.user.username) {
    return forbidden();
  }

  const parsed = await parseJsonBody(req);
  if (!parsed.ok) return parsed.response;

  const b = parsed.body;
  if (
    !isNonEmptyString(b.recipe_id) ||
    !isNonEmptyString(b.name) ||
    !isNonEmptyString(b.output_item) ||
    !Number.isInteger(b.output_quantity) ||
    (b.output_quantity as number) <= 0
  ) {
    return badRequest();
  }

  const result = createRecipe(id, {
    recipe_id: b.recipe_id as string,
    name: b.name as string,
    ingredients: b.ingredients as Record<string, number>,
    output_item: b.output_item as string,
    output_quantity: b.output_quantity as number,
  });

  if (result === "bad_request") {
    return badRequest();
  }
  if (result === "conflict") {
    return conflict();
  }

  return created(result);
}

export async function GET(
  req: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const auth = requireBearerAuth(req);
  if (!auth.ok) return auth.response;

  const { id } = await params;

  const campaign = getPlayCampaign(id);
  if (!campaign) {
    return notFound();
  }

  const members = getPlayCampaignMembers(id);
  const isOwner = campaign.owner === auth.user.username;
  const isMember = members.some((m) => m.username === auth.user.username);

  if (!isOwner && !isMember) {
    return forbidden();
  }

  return ok({ recipes: listRecipes(id) });
}
