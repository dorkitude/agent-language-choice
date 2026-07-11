import { badRequest, isRecord, json, readJson } from "../../../../api.js";
import {
  campaignCharacters,
  campaigns,
  isValidId,
  isValidLevel,
  isValidText,
  type CampaignCharacter,
} from "../../state.js";

export const runtime = "nodejs";

type RouteContext = {
  params: Promise<{ id: string }>;
};

export async function POST(request: Request, context: RouteContext) {
  const { id } = await context.params;
  if (campaigns.get(id) === undefined) {
    return json({ error: "not_found" }, 404);
  }

  const body = await readJson(request);
  if (
    !isRecord(body) ||
    !isValidId(body.id) ||
    !isValidText(body.name) ||
    !isValidLevel(body.level) ||
    !isValidText(body.class)
  ) {
    return badRequest();
  }

  if (campaignCharacters.has(id, body.id)) {
    return json({ error: "duplicate_id" }, 409);
  }

  const character: CampaignCharacter = {
    id: body.id,
    name: body.name,
    level: body.level,
    class: body.class,
  };
  campaignCharacters.create(id, character);

  return json(character, 201);
}
