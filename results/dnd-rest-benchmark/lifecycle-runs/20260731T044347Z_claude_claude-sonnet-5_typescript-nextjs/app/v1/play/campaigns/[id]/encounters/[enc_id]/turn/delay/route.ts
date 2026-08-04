import { requireSession } from "../../../../../../../auth/session.js";
import { parseJsonBody } from "../../../../../../../http.js";
import { requirePlayCampaign } from "../../../../../../http.js";
import {
  getPlayEncounter,
  getPlayEncounterTurnOrder,
  updatePlayEncounter,
  type PlayEncounterTurnEntry,
} from "../../../../../../store.js";

export async function POST(
  request: Request,
  { params }: { params: Promise<{ id: string; enc_id: string }> },
) {
  const { id: campaignId, enc_id: encounterId } = await params;

  const session = requireSession(request);
  if (!session.ok) return session.response;

  const campaign = requirePlayCampaign(campaignId);
  if (campaign instanceof Response) return campaign;

  const encounter = getPlayEncounter(campaignId, encounterId);
  if (!encounter) {
    return Response.json({ error: `encounter ${encounterId} not found` }, { status: 404 });
  }

  const order = getPlayEncounterTurnOrder(encounter);
  if (order.length === 0) {
    return Response.json({ error: `encounter ${encounterId} has no combatants` }, { status: 404 });
  }

  const turnIndex = (encounter.turn_index ?? 0) % order.length;
  const active = order[turnIndex];

  const username = session.user.username;
  const isCurrentCombatant = active.kind === "player" && active.member === username;
  const isOwner = username === campaign.owner;
  if (!isOwner && !isCurrentCombatant) {
    return Response.json(
      { error: `${username} may not delay the turn out of order` },
      { status: 409 },
    );
  }

  const parsed = await parseJsonBody(request);
  if (!parsed.ok) return parsed.response;
  const { new_index: newIndex } = (parsed.body ?? {}) as { new_index?: unknown };

  if (
    typeof newIndex !== "number" ||
    !Number.isInteger(newIndex) ||
    newIndex < 0 ||
    newIndex >= order.length
  ) {
    return Response.json({ error: `new_index must be an integer between 0 and ${order.length - 1}` }, { status: 400 });
  }

  const reordered = order.slice();
  const [moved] = reordered.splice(turnIndex, 1);
  reordered.splice(newIndex, 0, moved);

  const rank = new Map<string, number>();
  reordered.forEach((entry: PlayEncounterTurnEntry, index: number) => {
    rank.set(entry.target, reordered.length - index);
  });

  const combatants = encounter.combatants.map((combatant) => ({
    ...combatant,
    initiative: rank.get(combatant.member) ?? combatant.initiative,
  }));
  const monsters = (encounter.monsters ?? []).map((monster) => ({
    ...monster,
    initiative: rank.get(monster.monster_id) ?? monster.initiative,
  }));

  updatePlayEncounter({
    ...encounter,
    combatants,
    monsters,
    turn_index: newIndex,
  });

  return Response.json(
    {
      order: reordered.map((entry) => ({
        name: entry.name,
        kind: entry.kind,
        initiative: rank.get(entry.target) ?? entry.initiative,
      })),
    },
    { status: 200 },
  );
}
