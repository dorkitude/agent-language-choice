import { NextResponse } from "next/server";
import {
  derivedStats,
  type Abilities,
  type Armor,
} from "../../../lib/engine.js";
import { badRequest, parseJsonBody } from "../../../lib/http.js";

export async function POST(req: Request) {
  const parsed = await parseJsonBody(req);
  if (!parsed.ok) return parsed.response;

  const b = parsed.body;
  const level = Number(b.level);

  if (
    typeof b.abilities !== "object" ||
    b.abilities === null ||
    typeof b.armor !== "object" ||
    b.armor === null
  ) {
    return badRequest();
  }

  const rawAbilities = b.abilities as Record<string, unknown>;
  const abilities: Abilities = {
    str: Number(rawAbilities.str),
    dex: Number(rawAbilities.dex),
    con: Number(rawAbilities.con),
    int: Number(rawAbilities.int),
    wis: Number(rawAbilities.wis),
    cha: Number(rawAbilities.cha),
  };

  const rawArmor = b.armor as Record<string, unknown>;
  if (typeof rawArmor.shield !== "boolean") {
    return badRequest();
  }
  const armor: Armor = {
    base: Number(rawArmor.base),
    shield: rawArmor.shield,
    dex_cap: Number(rawArmor.dex_cap),
  };

  const result = derivedStats(level, abilities, armor);
  if (!result) {
    return badRequest();
  }

  return NextResponse.json(result);
}
