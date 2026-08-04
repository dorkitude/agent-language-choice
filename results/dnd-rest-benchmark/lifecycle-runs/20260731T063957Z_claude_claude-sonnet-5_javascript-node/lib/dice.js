// Parses "NdM+K" / "NdM-K" dice notation, e.g. "2d6+3".
export function parseDiceExpression(expression) {
  if (typeof expression !== 'string') return null;
  const match = /^(\d+)d(\d+)([+-]\d+)?$/.exec(expression.trim());
  if (!match) return null;
  const count = parseInt(match[1], 10);
  const sides = parseInt(match[2], 10);
  const modifier = match[3] ? parseInt(match[3], 10) : 0;
  if (count <= 0 || sides <= 0) return null;
  return { count, sides, modifier };
}
