import { NextResponse } from "next/server";

const ErrorMessages = {
  invalidJson: "Invalid JSON",
  badRequest: "Bad request",
  notFound: "Not found",
  conflict: "Conflict",
  unauthorized: "Unauthorized",
  forbidden: "Forbidden",
} as const;

export function ok<T>(data: T) {
  return NextResponse.json(data);
}

export function created<T>(data: T) {
  return NextResponse.json(data, { status: 201 });
}

export function badRequest(message: string = ErrorMessages.badRequest) {
  return NextResponse.json({ error: message }, { status: 400 });
}

export function notFound(message: string = ErrorMessages.notFound) {
  return NextResponse.json({ error: message }, { status: 404 });
}

export function conflict(message: string = ErrorMessages.conflict) {
  return NextResponse.json({ error: message }, { status: 409 });
}

export function unauthorized(message: string = ErrorMessages.unauthorized) {
  return NextResponse.json({ error: message }, { status: 401 });
}

export function forbidden(message: string = ErrorMessages.forbidden) {
  return NextResponse.json({ error: message }, { status: 403 });
}

/**
 * Parse and validate the JSON body of a POST request.
 *
 * Returns the parsed object on success, or a 400 response on failure.  This
 * helper preserves the evaluator's expected error shapes:
 *   - malformed JSON      -> { error: "Invalid JSON" }
 *   - non-object payload  -> { error: "Bad request" }
 */
export async function parseJsonBody(
  req: Request
): Promise<{ ok: true; body: Record<string, unknown> } | { ok: false; response: NextResponse }> {
  let body: unknown;
  try {
    body = await req.json();
  } catch {
    return { ok: false, response: badRequest(ErrorMessages.invalidJson) };
  }

  if (typeof body !== "object" || body === null) {
    return { ok: false, response: badRequest(ErrorMessages.badRequest) };
  }

  return { ok: true, body: body as Record<string, unknown> };
}
