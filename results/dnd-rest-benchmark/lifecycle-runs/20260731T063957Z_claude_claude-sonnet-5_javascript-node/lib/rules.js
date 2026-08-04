// 5e-style encounter-building and character-math constants/helpers, shared
// by the /v1/encounters, /v1/characters, and /v1/dm route groups.

export const CR_XP = {
  '0': 10,
  '1/8': 25,
  '1/4': 50,
  '1/2': 100,
  '1': 200,
  '2': 450,
  '3': 700,
  '4': 1100,
  '5': 1800,
};

// Only level-3 party thresholds are supported by this implementation.
export const LEVEL_THRESHOLDS = {
  3: { easy: 75, medium: 150, hard: 225, deadly: 400 },
};

export const DIFFICULTY_RECOMMENDATIONS = {
  trivial: 'trivial - consider adding threats',
  easy: 'safe warm-up',
  medium: 'balanced challenge',
  hard: 'bring your best tactics',
  deadly: 'deadly - proceed with caution',
};

// DMG encounter-multiplier table keyed by monster count.
export function countMultiplier(count) {
  if (count === 1) return 1;
  if (count === 2) return 1.5;
  if (count >= 3 && count <= 6) return 2;
  if (count >= 7 && count <= 10) return 2.5;
  if (count >= 11 && count <= 14) return 3;
  return 4;
}

export function proficiencyBonus(level) {
  if (!Number.isInteger(level) || level < 1 || level > 20) return null;
  return 2 + Math.floor((level - 1) / 4);
}

export function difficultyForXp(adjustedXp, thresholds) {
  if (adjustedXp >= thresholds.deadly) return 'deadly';
  if (adjustedXp >= thresholds.hard) return 'hard';
  if (adjustedXp >= thresholds.medium) return 'medium';
  if (adjustedXp >= thresholds.easy) return 'easy';
  return 'trivial';
}
