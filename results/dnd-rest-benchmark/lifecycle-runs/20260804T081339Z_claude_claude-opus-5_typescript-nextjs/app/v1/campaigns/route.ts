import { getCampaign, insertCampaign } from "../../../lib/campaigns";
import { badRequest, conflict, json, readObject } from "../../../lib/http";
import { isNonEmptyString, isValidId } from "../../../lib/validation";

export const dynamic = "force-dynamic";

export async function POST(request: Request): Promise<Response> {
  const body = await readObject(request);
  if (!body) return badRequest("body must be a JSON object");

  const { id, name, dm } = body;
  if (!isValidId(id)) return badRequest("id must be 1-64 characters of [A-Za-z0-9_.:-]");
  if (!isNonEmptyString(name)) return badRequest("name must be a non-empty string");
  if (!isNonEmptyString(dm)) return badRequest("dm must be a non-empty string");

  if (getCampaign(id)) return conflict("campaign id already exists");

  insertCampaign({ id, name, dm });
  return json({ id, name, dm }, 201);
}
