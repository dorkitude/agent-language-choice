export interface DiceStats {
  dice_count: number;
  sides: number;
  modifier: number;
  min: number;
  max: number;
  average: number;
}

export function parseDiceExpression(expression: string): {
  count: number;
  sides: number;
  modifier: number;
} | null {
  const match = /^(\d+)d(\d+)(?:([+-])(\d+))?$/.exec(expression.trim());
  if (!match) return null;
  const count = parseInt(match[1], 10);
  const sides = parseInt(match[2], 10);
  if (count <= 0 || sides <= 0) return null;
  let modifier = 0;
  if (match[3] && match[4]) {
    const value = parseInt(match[4], 10);
    modifier = match[3] === "-" ? -value : value;
  }
  return { count, sides, modifier };
}

export function computeDiceStats(expression: string): DiceStats | null {
  const parsed = parseDiceExpression(expression);
  if (!parsed) return null;
  const { count, sides, modifier } = parsed;
  const min = count * 1 + modifier;
  const max = count * sides + modifier;
  const average = (count * (sides + 1)) / 2 + modifier;
  return {
    dice_count: count,
    sides,
    modifier,
    min,
    max,
    average,
  };
}

export interface AbilityCheckResult {
  total: number;
  success: boolean;
  margin: number;
}

export function computeAbilityCheck(
  roll: number,
  modifier: number,
  dc: number
): AbilityCheckResult {
  const total = roll + modifier;
  return {
    total,
    success: total >= dc,
    margin: total - dc,
  };
}

const CR_XP: Record<string, number> = {
  "0": 10,
  "1/8": 25,
  "1/4": 50,
  "1/2": 100,
  "1": 200,
  "2": 450,
  "3": 700,
  "4": 1100,
  "5": 1800,
};

function multiplierForCount(count: number): number {
  if (count <= 1) return 1;
  if (count === 2) return 1.5;
  if (count <= 6) return 2;
  if (count <= 10) return 2.5;
  if (count <= 14) return 3;
  return 4;
}

const LEVEL_THRESHOLDS: Record<number, { easy: number; medium: number; hard: number; deadly: number }> = {
  3: { easy: 75, medium: 150, hard: 225, deadly: 400 },
};

export interface Monster {
  cr: string;
  count: number;
}

export interface PartyMember {
  level: number;
}

export interface AdjustedXpResult {
  base_xp: number;
  monster_count: number;
  multiplier: number;
  adjusted_xp: number;
  difficulty: string;
  thresholds: { easy: number; medium: number; hard: number; deadly: number };
}

export function computeAdjustedXp(
  party: PartyMember[],
  monsters: Monster[]
): AdjustedXpResult | null {
  let base_xp = 0;
  let monster_count = 0;
  for (const m of monsters) {
    const xp = CR_XP[m.cr];
    if (xp === undefined) return null;
    base_xp += xp * m.count;
    monster_count += m.count;
  }
  const multiplier = multiplierForCount(monster_count);
  const adjusted_xp = base_xp * multiplier;

  const thresholds = { easy: 0, medium: 0, hard: 0, deadly: 0 };
  for (const member of party) {
    const t = LEVEL_THRESHOLDS[member.level];
    if (!t) return null;
    thresholds.easy += t.easy;
    thresholds.medium += t.medium;
    thresholds.hard += t.hard;
    thresholds.deadly += t.deadly;
  }

  let difficulty = "trivial";
  if (adjusted_xp >= thresholds.deadly) difficulty = "deadly";
  else if (adjusted_xp >= thresholds.hard) difficulty = "hard";
  else if (adjusted_xp >= thresholds.medium) difficulty = "medium";
  else if (adjusted_xp >= thresholds.easy) difficulty = "easy";

  return {
    base_xp,
    monster_count,
    multiplier,
    adjusted_xp,
    difficulty,
    thresholds,
  };
}

export interface Combatant {
  name: string;
  dex: number;
  roll: number;
}

export interface InitiativeEntry {
  name: string;
  score: number;
}

export function computeAbilityModifier(score: number): number {
  return Math.floor((score - 10) / 2);
}

export function isValidAbilityScore(score: unknown): score is number {
  return typeof score === "number" && Number.isInteger(score) && score >= 1 && score <= 30;
}

export function computeProficiencyBonus(level: number): number {
  return 2 + Math.floor((level - 1) / 4);
}

export function isValidLevel(level: unknown): level is number {
  return typeof level === "number" && Number.isInteger(level) && level >= 1 && level <= 20;
}

export interface Abilities {
  str: number;
  dex: number;
  con: number;
  int: number;
  wis: number;
  cha: number;
}

export interface Armor {
  base: number;
  shield: boolean;
  dex_cap: number;
}

export interface DerivedStatsResult {
  level: number;
  proficiency_bonus: number;
  hp_max: number;
  armor_class: number;
  modifiers: Abilities;
}

export function computeDerivedStats(
  level: number,
  abilities: Abilities,
  armor: Armor
): DerivedStatsResult {
  const modifiers: Abilities = {
    str: computeAbilityModifier(abilities.str),
    dex: computeAbilityModifier(abilities.dex),
    con: computeAbilityModifier(abilities.con),
    int: computeAbilityModifier(abilities.int),
    wis: computeAbilityModifier(abilities.wis),
    cha: computeAbilityModifier(abilities.cha),
  };
  const proficiency_bonus = computeProficiencyBonus(level);
  const hp_max = level * (6 + modifiers.con);
  const shield_bonus = armor.shield ? 2 : 0;
  const armor_class = armor.base + Math.min(modifiers.dex, armor.dex_cap) + shield_bonus;
  return {
    level,
    proficiency_bonus,
    hp_max,
    armor_class,
    modifiers,
  };
}

export function computeInitiativeOrder(combatants: Combatant[]): InitiativeEntry[] {
  const scored = combatants.map((c) => ({
    name: c.name,
    dex: c.dex,
    score: c.roll + c.dex,
  }));
  scored.sort((a, b) => {
    if (b.score !== a.score) return b.score - a.score;
    if (b.dex !== a.dex) return b.dex - a.dex;
    return a.name.localeCompare(b.name);
  });
  return scored.map((c) => ({ name: c.name, score: c.score }));
}

export interface CombatCondition {
  condition: string;
  remaining_rounds: number;
}

export interface CombatSessionState {
  id: string;
  round: number;
  turn_index: number;
  order: InitiativeEntry[];
  conditions: Record<string, CombatCondition[]>;
}

export function createCombatSession(id: string, combatants: Combatant[]): CombatSessionState {
  const order = computeInitiativeOrder(combatants);
  return {
    id,
    round: 1,
    turn_index: 0,
    order,
    conditions: {},
  };
}

export function activeCombatant(session: CombatSessionState): InitiativeEntry {
  return session.order[session.turn_index];
}

export function addCombatCondition(
  session: CombatSessionState,
  target: string,
  condition: string,
  duration_rounds: number
): CombatCondition[] {
  const list = session.conditions[target] ?? [];
  list.push({ condition, remaining_rounds: duration_rounds });
  session.conditions[target] = list;
  return list;
}

export function advanceCombatTurn(session: CombatSessionState): void {
  session.turn_index += 1;
  if (session.turn_index >= session.order.length) {
    session.turn_index = 0;
    session.round += 1;
  }
  const active = activeCombatant(session);
  const list = session.conditions[active.name];
  if (list) {
    const remaining: CombatCondition[] = [];
    for (const c of list) {
      const next = c.remaining_rounds - 1;
      if (next > 0) remaining.push({ condition: c.condition, remaining_rounds: next });
    }
    session.conditions[active.name] = remaining;
  }
}
