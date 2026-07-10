import { abilityModifier, isInt } from "../_lib.js";

function badRequest(message: string) {
  return Response.json({ error: message }, { status: 400 });
}

export async function POST(request: Request) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return badRequest("invalid JSON body");
  }

  if (typeof body !== "object" || body === null) {
    return badRequest("body must be an object");
  }

  const { score } = body as { score?: unknown };

  if (!isInt(score) || score < 1 || score > 30) {
    return badRequest("score must be an integer from 1 through 30");
  }

  return Response.json({ score, modifier: abilityModifier(score) });
}
