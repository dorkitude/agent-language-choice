import { badRequest, isRecord, json, readJson } from "../../api.js";
import { campaigns, isValidId, isValidText, type Campaign } from "./state.js";

export const runtime = "nodejs";

export async function POST(request: Request) {
  const body = await readJson(request);
  if (!isRecord(body) || !isValidId(body.id) || !isValidText(body.name) || !isValidText(body.dm)) {
    return badRequest();
  }

  if (campaigns.has(body.id)) {
    return json({ error: "duplicate_id" }, 409);
  }

  const campaign: Campaign = {
    id: body.id,
    name: body.name,
    dm: body.dm,
  };
  campaigns.create(campaign);

  return json(campaign, 201);
}
