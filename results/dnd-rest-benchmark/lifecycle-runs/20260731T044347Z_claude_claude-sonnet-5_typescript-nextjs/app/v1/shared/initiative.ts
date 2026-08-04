/**
 * Initiative ranking shared by the combat-session and standalone initiative
 * endpoints. Both features compute the same "score = roll + dex" ordering
 * with the same tie-break rules, so the logic lives here once.
 */
export interface InitiativeInput {
  name: string;
  dex: number;
  roll: number;
}

export interface InitiativeEntry {
  name: string;
  dex: number;
  score: number;
}

/**
 * Ranks combatants by initiative score (roll + dex), highest first.
 * Ties are broken by higher dex, then alphabetically by name.
 */
export function rankInitiative(combatants: InitiativeInput[]): InitiativeEntry[] {
  const scored = combatants.map((combatant) => ({
    name: combatant.name,
    dex: combatant.dex,
    score: combatant.roll + combatant.dex,
  }));

  scored.sort((a, b) => {
    if (b.score !== a.score) return b.score - a.score;
    if (b.dex !== a.dex) return b.dex - a.dex;
    return a.name.localeCompare(b.name);
  });

  return scored;
}
