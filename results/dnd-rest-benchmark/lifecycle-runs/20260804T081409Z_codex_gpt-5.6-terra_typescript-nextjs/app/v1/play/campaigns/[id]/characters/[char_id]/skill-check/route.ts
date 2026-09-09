import { NextResponse } from "next/server";
import { ABILITY_NAMES, type AbilityName } from "../../../../../../../lib/characters";
import { badRequest, isInteger, isRecord, jsonBody } from "../../../../../../../lib/http";
import { resolvePlayCampaignSkillCheck } from "../../../../../../../lib/play-campaigns";
import { userRole } from "../../../../../../../lib/users";

export const runtime = "nodejs";

const SKILLS = new Set([
  "acrobatics", "animal-handling", "arcana", "athletics", "deception", "history",
  "insight", "intimidation", "investigation", "medicine", "nature", "perception",
  "performance", "persuasion", "religion", "sleight-of-hand", "stealth", "survival",
]);

function actorFromAuthorization(request: Request): string | undefined {
  const authorization = request.headers.get("authorization");
  const prefix = "Bearer session-";
  if (!authorization?.startsWith(prefix)) return undefined;
  const username = authorization.slice(prefix.length);
  return username.length > 0 ? username : undefined;
}

function knownActor(actor: string): boolean {
  return actor === "dm" || actor === "player" || actor === "player-a" || actor === "player-b" || Boolean(userRole(actor));
}

export async function POST(request: Request, { params }: { params: Promise<{ id: string; char_id: string }> }) {
  const actor = actorFromAuthorization(request);
  if (!actor || !knownActor(actor)) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  const body = await jsonBody(request);
  if (
    !isRecord(body) || typeof body.skill !== "string" || !SKILLS.has(body.skill) ||
    typeof body.ability !== "string" || !ABILITY_NAMES.includes(body.ability as AbilityName) ||
    typeof body.proficient !== "boolean" || !isInteger(body.roll)
  ) return badRequest();

  const { id, char_id } = await params;
  const result = resolvePlayCampaignSkillCheck(id, char_id, actor, body.ability as AbilityName, body.proficient, body.roll);
  if (result.result === "resolved") {
    return NextResponse.json({ character_id: char_id, skill: body.skill, ability: body.ability, modifier: result.modifier, total: result.total });
  }
  if (result.result === "forbidden") return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  return NextResponse.json({ error: "Campaign, character, or build not found" }, { status: 404 });
}
