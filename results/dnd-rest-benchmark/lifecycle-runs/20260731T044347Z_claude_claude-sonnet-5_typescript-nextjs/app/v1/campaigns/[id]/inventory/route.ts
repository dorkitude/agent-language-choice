import { CampaignInventoryItem, createCampaignInventoryItem } from "../../store.js";
import { requireCampaign } from "../../http.js";
import { parseJsonBody, requireNonEmptyString } from "../../../http.js";

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id: campaignId } = await params;

  const campaign = requireCampaign(campaignId);
  if (campaign instanceof Response) return campaign;

  const parsed = await parseJsonBody(request);
  if (!parsed.ok) return parsed.response;
  const body = parsed.body;

  const { item_slug, quantity, owner } = (body ?? {}) as {
    item_slug?: unknown;
    quantity?: unknown;
    owner?: unknown;
  };

  const validItemSlug = requireNonEmptyString(item_slug, "item_slug");
  if (validItemSlug instanceof Response) return validItemSlug;

  if (typeof quantity !== "number" || !Number.isInteger(quantity) || quantity < 1) {
    return Response.json({ error: "quantity must be a positive integer" }, { status: 400 });
  }

  const validOwner = requireNonEmptyString(owner, "owner");
  if (validOwner instanceof Response) return validOwner;

  const item: CampaignInventoryItem = { item_slug: validItemSlug, quantity, owner: validOwner };
  createCampaignInventoryItem(campaignId, item);

  return Response.json(item, { status: 201 });
}
