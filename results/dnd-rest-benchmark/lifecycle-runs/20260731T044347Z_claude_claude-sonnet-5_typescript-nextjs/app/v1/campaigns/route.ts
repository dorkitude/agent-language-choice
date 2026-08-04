import { Campaign, createCampaign, hasCampaign } from "./store.js";
import { parseJsonBody, requireNonEmptyString } from "../http.js";

export async function POST(request: Request) {
  const parsed = await parseJsonBody(request);
  if (!parsed.ok) return parsed.response;
  const body = parsed.body;

  const { id, name, dm } = (body ?? {}) as { id?: unknown; name?: unknown; dm?: unknown };

  const validId = requireNonEmptyString(id, "id");
  if (validId instanceof Response) return validId;

  const validName = requireNonEmptyString(name, "name");
  if (validName instanceof Response) return validName;

  const validDm = requireNonEmptyString(dm, "dm");
  if (validDm instanceof Response) return validDm;

  if (hasCampaign(validId)) {
    return Response.json({ error: `campaign ${validId} already exists` }, { status: 409 });
  }

  const campaign: Campaign = { id: validId, name: validName, dm: validDm };
  createCampaign(campaign);

  return Response.json(campaign, { status: 201 });
}
