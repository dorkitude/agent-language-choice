import { listCampaignEquipment, listCampaignInventory } from "../../../store.js";
import { requireCampaign } from "../../../http.js";

const HEALING_POTION_SLUG = "healing-potion";

export async function GET(_request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id: campaignId } = await params;

  const campaign = requireCampaign(campaignId);
  if (campaign instanceof Response) return campaign;

  const inventory = listCampaignInventory(campaignId);
  const equipment = listCampaignEquipment(campaignId);

  const partyItems = inventory.filter((item) => item.owner === "party").length;
  const assignedItems = equipment.length;

  const healingPotionsInParty = inventory
    .filter((item) => item.owner === "party" && item.item_slug === HEALING_POTION_SLUG)
    .reduce((sum, item) => sum + item.quantity, 0);
  const healingPotionsAssigned = equipment
    .filter((assignment) => assignment.item_slug === HEALING_POTION_SLUG)
    .reduce((sum, assignment) => sum + assignment.quantity, 0);

  const summary = {
    campaign_id: campaignId,
    party_items: partyItems,
    assigned_items: assignedItems,
    healing_potions_available: healingPotionsInParty - healingPotionsAssigned,
  };

  return Response.json(summary);
}
