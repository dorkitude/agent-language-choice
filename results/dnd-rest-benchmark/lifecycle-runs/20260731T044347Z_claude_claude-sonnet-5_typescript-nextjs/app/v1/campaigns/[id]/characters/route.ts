import {
  CampaignCharacter,
  createCampaignCharacter,
  hasCampaignCharacter,
} from "../../store.js";
import { requireCampaign } from "../../http.js";
import { parseJsonBody, requireNonEmptyString } from "../../../http.js";

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id: campaignId } = await params;

  const campaign = requireCampaign(campaignId);
  if (campaign instanceof Response) return campaign;

  const parsed = await parseJsonBody(request);
  if (!parsed.ok) return parsed.response;
  const body = parsed.body;

  const { id, name, level, class: charClass } = (body ?? {}) as {
    id?: unknown;
    name?: unknown;
    level?: unknown;
    class?: unknown;
  };

  const validId = requireNonEmptyString(id, "id");
  if (validId instanceof Response) return validId;

  const validName = requireNonEmptyString(name, "name");
  if (validName instanceof Response) return validName;

  if (typeof level !== "number" || !Number.isInteger(level) || level < 1) {
    return Response.json({ error: "level must be a positive integer" }, { status: 400 });
  }

  const validClass = requireNonEmptyString(charClass, "class");
  if (validClass instanceof Response) return validClass;

  if (hasCampaignCharacter(campaignId, validId)) {
    return Response.json(
      { error: `character ${validId} already exists in campaign ${campaignId}` },
      { status: 409 },
    );
  }

  const character: CampaignCharacter = { id: validId, name: validName, level, class: validClass };
  createCampaignCharacter(campaignId, character);

  return Response.json(character, { status: 201 });
}
