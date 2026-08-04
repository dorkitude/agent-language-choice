/** Wizard (full caster) spell slots per spell level, indexed by character level. */
const FULL_CASTER_SLOTS: Record<number, number[]> = {
  1: [2],
  2: [3],
  3: [4, 2],
  4: [4, 3],
  5: [4, 3, 2],
  6: [4, 3, 3],
  7: [4, 3, 3, 1],
  8: [4, 3, 3, 2],
  9: [4, 3, 3, 3, 1],
  10: [4, 3, 3, 3, 2],
  11: [4, 3, 3, 3, 2, 1],
  12: [4, 3, 3, 3, 2, 1],
  13: [4, 3, 3, 3, 2, 1, 1],
  14: [4, 3, 3, 3, 2, 1, 1],
  15: [4, 3, 3, 3, 2, 1, 1, 1],
  16: [4, 3, 3, 3, 2, 1, 1, 1],
  17: [4, 3, 3, 3, 2, 1, 1, 1, 1],
  18: [4, 3, 3, 3, 3, 1, 1, 1, 1],
  19: [4, 3, 3, 3, 3, 2, 1, 1, 1],
  20: [4, 3, 3, 3, 3, 2, 2, 1, 1],
};

const FULL_CASTERS = new Set(["wizard"]);

/** Spell slots for a class/level, or undefined when the class is unsupported. */
export function spellSlots(
  className: string,
  level: number,
): Record<string, number> | undefined {
  if (!FULL_CASTERS.has(className)) return undefined;
  const row = FULL_CASTER_SLOTS[level];
  if (!row) return undefined;
  const slots: Record<string, number> = {};
  row.forEach((count, index) => {
    if (count > 0) slots[String(index + 1)] = count;
  });
  return slots;
}

/** Hit dice recovered on a long rest: half the character level, minimum 1. */
export function hitDiceRecovered(level: number): number {
  return Math.max(1, Math.floor(level / 2));
}
