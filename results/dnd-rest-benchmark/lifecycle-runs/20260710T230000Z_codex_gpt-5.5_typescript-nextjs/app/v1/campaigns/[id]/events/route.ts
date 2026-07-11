import { badRequest, isRecord, json, readJson } from "../../../../api.js";
import { campaignEvents, campaigns, isValidId, isValidText, type CampaignEvent } from "../../state.js";

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
  if (!isRecord(body) || !isValidId(body.id) || !isValidText(body.kind) || !isValidText(body.summary)) {
    return badRequest();
  }

  if (campaignEvents.has(id, body.id)) {
    return json({ error: "duplicate_id" }, 409);
  }

  const event: CampaignEvent = {
    id: body.id,
    kind: body.kind,
    summary: body.summary,
  };
  campaignEvents.create(id, event);

  return json(
    {
      id: event.id,
      kind: event.kind,
    },
    201,
  );
}
