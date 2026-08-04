/**
 * HTTP plumbing shared by every route handler: JSON response builders and
 * request-body reading. Payload validation lives in `./validation`.
 *
 * Every error response has the same shape, `{"error": "..."}`, so clients can
 * read failures uniformly regardless of which endpoint produced them.
 */
import { isObject } from "./validation";

export function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

export function badRequest(message = "invalid request"): Response {
  return json({ error: message }, 400);
}

export function unauthorized(message = "invalid credentials"): Response {
  return json({ error: message }, 401);
}

export function notFound(message = "not found"): Response {
  return json({ error: message }, 404);
}

export function conflict(message = "already exists"): Response {
  return json({ error: message }, 409);
}

/**
 * Parse a JSON request body. Returns undefined when the body is malformed or
 * is not a JSON object — arrays and bare scalars are rejected — which callers
 * turn into a 400.
 */
export async function readObject(
  request: Request,
): Promise<Record<string, unknown> | undefined> {
  let parsed: unknown;
  try {
    parsed = await request.json();
  } catch {
    return undefined;
  }
  return isObject(parsed) ? parsed : undefined;
}
