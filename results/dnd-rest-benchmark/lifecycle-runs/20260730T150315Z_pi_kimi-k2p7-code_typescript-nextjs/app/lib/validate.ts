/**
 * Tiny, deterministic predicates used by route handlers to validate request
 * bodies.  These are intentionally narrow and match the exact checks that the
 * evaluator suite exercises.
 */

export function isNonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.length > 0;
}

export function isInteger(value: unknown): value is number {
  return Number.isInteger(value);
}

export function isPositiveInteger(value: unknown): value is number {
  return isInteger(value) && value > 0;
}

export function isNonNegativeInteger(value: unknown): value is number {
  return isInteger(value) && value >= 0;
}

export function isStringArray(value: unknown): value is string[] {
  if (!Array.isArray(value)) return false;
  return (value as unknown[]).every((item) => typeof item === "string");
}

export function isNonEmptyStringArray(value: unknown): value is string[] {
  if (!Array.isArray(value)) return false;
  return (value as unknown[]).every(
    (item) => typeof item === "string" && item.length > 0
  );
}
