// Initiative ordering and per-round condition bookkeeping for combat sessions.

export function computeOrder(combatants) {
  const scored = combatants.map((c) => ({
    name: c.name,
    dex: c.dex,
    score: c.roll + c.dex,
    conditions: [],
  }));
  scored.sort((a, b) => {
    if (b.score !== a.score) return b.score - a.score;
    if (b.dex !== a.dex) return b.dex - a.dex;
    return a.name < b.name ? -1 : a.name > b.name ? 1 : 0;
  });
  return scored;
}

export function activeSummary(session) {
  const active = session.order[session.turn_index];
  return { name: active.name, score: active.score };
}

export function conditionsSummary(session) {
  const result = {};
  for (const combatant of session.order) {
    if (combatant.conditions.length > 0) {
      result[combatant.name] = combatant.conditions.map((c) => ({
        condition: c.condition,
        remaining_rounds: c.remaining_rounds,
      }));
    }
  }
  return result;
}
