import { NextResponse } from "next/server";
import { ABILITY_NAMES, isAbilityScore } from "../../../../../../../lib/characters";
import { badRequest, isRecord, jsonBody } from "../../../../../../../lib/http";
import { buildPlayCampaignCharacter } from "../../../../../../../lib/play-campaigns";
import { userRole } from "../../../../../../../lib/users";

export const runtime = "nodejs";

const RACES = new Set(["dwarf", "elf", "halfling", "human", "dragonborn", "gnome", "half-elf", "half-orc", "tiefling"]);
const CLASSES = new Set(["barbarian", "bard", "cleric", "druid", "fighter", "monk", "paladin", "ranger", "rogue", "sorcerer", "warlock", "wizard"]);
const BACKGROUNDS = new Set(["acolyte", "charlatan", "criminal", "entertainer", "folk-hero", "guild-artisan", "hermit", "noble", "outlander", "sage", "sailor", "soldier", "urchin"]);

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
    !isRecord(body) ||
    typeof body.race !== "string" || !RACES.has(body.race) ||
    typeof body.class !== "string" || !CLASSES.has(body.class) ||
    typeof body.background !== "string" || !BACKGROUNDS.has(body.background) ||
    !isRecord(body.abilities)
  ) return badRequest();

  for (const ability of ABILITY_NAMES) {
    if (!isAbilityScore(body.abilities[ability])) return badRequest();
  }
  const con = body.abilities.con;
  if (!isAbilityScore(con)) return badRequest();

  const { id, char_id } = await params;
  const result = buildPlayCampaignCharacter(id, char_id, actor, {
    race: body.race,
    class: body.class,
    background: body.background,
    abilities: {
      str: body.abilities.str as number,
      dex: body.abilities.dex as number,
      con,
      int: body.abilities.int as number,
      wis: body.abilities.wis as number,
      cha: body.abilities.cha as number,
    },
  });
  if (result.result === "built") return NextResponse.json(result.character);
  if (result.result === "forbidden") return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  return NextResponse.json({ error: "Campaign or character not found" }, { status: 404 });
}
