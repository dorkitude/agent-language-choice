/**
 * Request-payload validators shared by every route handler.
 *
 * These are pure predicates and coercions: they never touch the database and
 * never build a `Response`. Routes own the wording of their 400s, so each
 * helper reports failure as `false`/`undefined` rather than an error message.
 * Keeping the gates here is what makes the same field accept the same inputs
 * across endpoints.
 */

export function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * A non-null object, arrays included. Looser than `isObject`, and used for
 * entries inside a list payload: a malformed entry is then reported by the
 * field it is missing rather than by its container type, which is the wording
 * these endpoints have always returned.
 */
export function isObjectLike(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

export function isNonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

/** Campaign/character/event ids travel in URL path segments, so they stay in a safe character set. */
export function isValidId(value: unknown): value is string {
  return typeof value === "string" && /^[A-Za-z0-9_.:-]{1,64}$/.test(value);
}

/** Compendium slugs are path segments too, with a stricter set (no dots or colons). */
export function isValidSlug(value: unknown): value is string {
  return typeof value === "string" && /^[A-Za-z0-9_-]{1,64}$/.test(value);
}

/**
 * Accept an integer, or a string that is exactly an integer. Floats, booleans,
 * `null` and objects are all rejected — a JSON `1.5` is never silently rounded.
 */
export function asInteger(value: unknown): number | undefined {
  if (typeof value === "number") {
    return Number.isInteger(value) ? value : undefined;
  }
  if (typeof value === "string" && /^[+-]?\d+$/.test(value.trim())) {
    return Number.parseInt(value.trim(), 10);
  }
  return undefined;
}

/** An integer bounded on both sides, e.g. ability scores (1-30) and levels (1-20). */
export function asIntegerInRange(
  value: unknown,
  minimum: number,
  maximum: number,
): number | undefined {
  const parsed = asInteger(value);
  if (parsed === undefined || parsed < minimum || parsed > maximum) return undefined;
  return parsed;
}

/** An integer with only a lower bound, e.g. counts (>= 0) and quantities (>= 1). */
export function asCount(value: unknown, minimum: number): number | undefined {
  const parsed = asInteger(value);
  if (parsed === undefined || parsed < minimum) return undefined;
  return parsed;
}

/** Character levels are positive integers; shared so the 400s stay consistent. */
export function asLevel(value: unknown): number | undefined {
  return asCount(value, 1);
}

/** Accept a number, or a string that parses as a finite number. Fractions allowed. */
export function asFiniteNumber(value: unknown): number | undefined {
  if (typeof value === "number") return Number.isFinite(value) ? value : undefined;
  if (typeof value === "string" && value.trim() !== "") {
    const parsed = Number(value.trim());
    return Number.isFinite(parsed) ? parsed : undefined;
  }
  return undefined;
}
