import { badRequest, isFiniteNumber, isRecord, json, readJson } from "../../../api.js";

export async function POST(request: Request) {
  const body = await readJson(request);
  if (!isRecord(body) || !Array.isArray(body.combatants)) {
    return badRequest();
  }

  const order = [];
  for (const combatant of body.combatants) {
    if (
      !isRecord(combatant) ||
      typeof combatant.name !== "string" ||
      !isFiniteNumber(combatant.dex) ||
      !isFiniteNumber(combatant.roll)
    ) {
      return badRequest();
    }

    order.push({
      name: combatant.name,
      dex: combatant.dex,
      score: combatant.roll + combatant.dex,
    });
  }

  order.sort((a, b) => b.score - a.score || b.dex - a.dex || a.name.localeCompare(b.name));

  return json({
    order: order.map(({ name, score }) => ({ name, score })),
  });
}
