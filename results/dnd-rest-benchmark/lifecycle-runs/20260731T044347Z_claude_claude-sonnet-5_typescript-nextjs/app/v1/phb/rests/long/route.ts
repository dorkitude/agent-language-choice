import { parseJsonBody } from "../../../http.js";

export async function POST(request: Request) {
  const parsed = await parseJsonBody(request);
  if (!parsed.ok) return parsed.response;
  const body = parsed.body;

  const { level, hp_current, hp_max, hit_dice_spent, exhaustion_level } = (body ?? {}) as {
    level?: unknown;
    hp_current?: unknown;
    hp_max?: unknown;
    hit_dice_spent?: unknown;
    exhaustion_level?: unknown;
  };

  if (
    typeof level !== "number" ||
    typeof hp_current !== "number" ||
    typeof hp_max !== "number" ||
    typeof hit_dice_spent !== "number" ||
    typeof exhaustion_level !== "number"
  ) {
    return Response.json(
      { error: "level, hp_current, hp_max, hit_dice_spent, and exhaustion_level must be numbers" },
      { status: 400 }
    );
  }

  const maxRecoverable = Math.max(1, Math.floor(level / 2));
  const recovered = Math.min(maxRecoverable, hit_dice_spent);
  const newHitDiceSpent = Math.max(0, hit_dice_spent - recovered);
  const newExhaustion = Math.max(0, exhaustion_level - 1);

  return Response.json({
    hp_current: hp_max,
    hit_dice_spent: newHitDiceSpent,
    exhaustion_level: newExhaustion,
  });
}
