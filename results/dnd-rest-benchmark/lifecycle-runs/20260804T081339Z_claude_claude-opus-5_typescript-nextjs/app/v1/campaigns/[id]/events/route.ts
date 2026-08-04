import { getCampaign, getEvent, insertEvent } from "../../../../../lib/campaigns";
import { badRequest, conflict, json, notFound, readObject } from "../../../../../lib/http";
import { isNonEmptyString, isValidId } from "../../../../../lib/validation";

export const dynamic = "force-dynamic";

export async function POST(
  request: Request,
  context: { params: Promise<{ id: string }> },
): Promise<Response> {
  const { id: campaignId } = await context.params;
  if (!getCampaign(campaignId)) return notFound("unknown campaign");

  const body = await readObject(request);
  if (!body) return badRequest("body must be a JSON object");

  const { id, kind, summary } = body;
  if (!isValidId(id)) return badRequest("id must be 1-64 characters of [A-Za-z0-9_.:-]");
  if (!isNonEmptyString(kind)) return badRequest("kind must be a non-empty string");
  if (summary !== undefined && typeof summary !== "string") {
    return badRequest("summary must be a string");
  }

  if (getEvent(campaignId, id)) return conflict("event id already exists");

  insertEvent(campaignId, { id, kind, summary: summary ?? "" });
  return json({ id, kind }, 201);
}
