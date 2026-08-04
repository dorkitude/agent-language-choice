/**
 * Shared HTTP helpers for v1 route handlers.
 *
 * Every mutating endpoint in this API accepts a JSON request body and must
 * respond with `400 { error: "invalid JSON body" }` when the body cannot be
 * parsed as JSON. This helper centralizes that contract so individual route
 * handlers only need to check the `ok` discriminant instead of repeating the
 * same try/catch boilerplate.
 */
export type JsonBodyResult = { ok: true; body: unknown } | { ok: false; response: Response };

export async function parseJsonBody(request: Request): Promise<JsonBodyResult> {
  try {
    const body = await request.json();
    return { ok: true, body };
  } catch {
    return {
      ok: false,
      response: Response.json({ error: "invalid JSON body" }, { status: 400 }),
    };
  }
}

/**
 * Validates that a request-body field is a non-empty string, using the
 * `"<fieldName> must be a non-empty string"` 400 shape that every route in
 * this API repeats by hand for its string fields. Returns the validated
 * string on success, or the Response to return on failure.
 */
export function requireNonEmptyString(value: unknown, fieldName: string): string | Response {
  if (typeof value !== "string" || value.length === 0) {
    return Response.json({ error: `${fieldName} must be a non-empty string` }, { status: 400 });
  }
  return value;
}
