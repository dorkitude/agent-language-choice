// Request-body validation helpers shared across route handlers.

export function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function isValidInt(value: unknown, min: number, max: number): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= min && value <= max;
}

// Shared slug pattern for compendium/inventory item slugs: lowercase
// alphanumeric segments joined by single hyphens (e.g. "longsword", "potion-of-healing").
export const SLUG_RE = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
