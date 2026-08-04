import {
  getCampaign,
  getCharacter,
  insertCharacter,
} from "../../../../../lib/campaigns";
import { badRequest, conflict, json, notFound, readObject } from "../../../../../lib/http";
import { asLevel, isNonEmptyString, isValidId } from "../../../../../lib/validation";

export const dynamic = "force-dynamic";

export async function POST(
  request: Request,
  context: { params: Promise<{ id: string }> },
): Promise<Response> {
  const { id: campaignId } = await context.params;
  if (!getCampaign(campaignId)) return notFound("unknown campaign");

  const body = await readObject(request);
  if (!body) return badRequest("body must be a JSON object");

  const { id, name } = body;
  const characterClass = body.class;
  if (!isValidId(id)) return badRequest("id must be 1-64 characters of [A-Za-z0-9_.:-]");
  if (!isNonEmptyString(name)) return badRequest("name must be a non-empty string");

  const level = asLevel(body.level);
  if (level === undefined) return badRequest("level must be a positive integer");
  if (!isNonEmptyString(characterClass)) return badRequest("class must be a non-empty string");

  if (getCharacter(campaignId, id)) return conflict("character id already exists");

  insertCharacter(campaignId, { id, name, level, class: characterClass });
  return json({ id, name, level, class: characterClass }, 201);
}
