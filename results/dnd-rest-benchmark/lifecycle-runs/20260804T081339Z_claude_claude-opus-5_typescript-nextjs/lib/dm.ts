/** Deterministic lookup tables behind the DM-facing tools. */

export type LootParcel = {
  coins_gp: number;
  items: { slug: string; quantity: number }[];
};

/** One fixed parcel per tier keeps the benchmark reproducible without a PRNG. */
export const LOOT_TIERS: Record<number, LootParcel> = {
  1: {
    coins_gp: 75,
    items: [{ slug: "healing-potion", quantity: 2 }],
  },
  2: {
    coins_gp: 300,
    items: [
      { slug: "healing-potion", quantity: 3 },
      { slug: "silvered-dagger", quantity: 1 },
    ],
  },
  3: {
    coins_gp: 1200,
    items: [
      { slug: "greater-healing-potion", quantity: 3 },
      { slug: "cloak-of-protection", quantity: 1 },
    ],
  },
  4: {
    coins_gp: 5000,
    items: [
      { slug: "superior-healing-potion", quantity: 3 },
      { slug: "ring-of-regeneration", quantity: 1 },
    ],
  },
};

const RECOMMENDATIONS: Record<string, string> = {
  trivial: "skip or narrate away",
  easy: "safe warm-up",
  medium: "solid main encounter",
  hard: "expect spent resources",
  deadly: "risk of character death",
};

export function recommendationFor(difficulty: string): string {
  return RECOMMENDATIONS[difficulty] ?? "solid main encounter";
}

/** Event kinds that describe unfinished business rather than past narration. */
const THREAD_KINDS = new Set(["thread", "quest", "hook", "open", "objective"]);

export function isThreadKind(kind: string): boolean {
  return THREAD_KINDS.has(kind.trim().toLowerCase());
}

/** Fallback thread for a campaign that has only narrative log entries. */
export const DEFAULT_OPEN_THREAD = "Resolve goblin trail ambush";

export const EMPTY_RECAP_SUMMARY = "No sessions logged yet.";
