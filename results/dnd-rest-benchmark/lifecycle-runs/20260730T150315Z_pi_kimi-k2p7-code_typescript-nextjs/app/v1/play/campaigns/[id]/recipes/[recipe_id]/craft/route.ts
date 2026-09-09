import { requireBearerAuth } from "../../../../../../../lib/auth.js";
import {
  badRequest,
  conflict,
  created,
  forbidden,
  notFound,
  parseJsonBody,
} from "../../../../../../../lib/http.js";
import {
  craftRecipe,
  getCharacterOwner,
  getPlayCampaign,
  getRecipe,
} from "../../../../../../../lib/storage.js";
import { isNonEmptyString } from "../../../../../../../lib/validate.js";

export const dynamic = "force-dynamic";

export async function POST(
  req: Request,
  { params }: { params: Promise<{ id: string; recipe_id: string }> }
) {
  const auth = requireBearerAuth(req);
  if (!auth.ok) return auth.response;

  const { id, recipe_id } = await params;

  const campaign = getPlayCampaign(id);
  if (!campaign) {
    return notFound();
  }

  const recipe = getRecipe(id, recipe_id);
  if (!recipe) {
    return notFound();
  }

  const parsed = await parseJsonBody(req);
  if (!parsed.ok) return parsed.response;

  const b = parsed.body;
  if (!isNonEmptyString(b.character_id)) {
    return badRequest();
  }
  const characterId = b.character_id as string;

  const ownerRecord = getCharacterOwner(id, characterId);
  if (!ownerRecord) {
    return notFound();
  }

  const isOwner = campaign.owner === auth.user.username;
  if (isOwner) {
    return forbidden();
  }

  if (!ownerRecord.owner || ownerRecord.owner !== auth.user.username) {
    return forbidden();
  }

  const result = craftRecipe(id, recipe_id, characterId);

  if (result === "not_found") {
    return notFound();
  }
  if (result === "invalid") {
    return badRequest();
  }
  if (result === "insufficient") {
    return conflict();
  }

  return created(result);
}
