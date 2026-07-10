import { isInt, proficiencyBonus } from "../_lib.js";

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

  const { level } = body as { level?: unknown };

  if (!isInt(level) || level < 1 || level > 20) {
    return badRequest("level must be an integer from 1 through 20");
  }

  return Response.json({ level, proficiency_bonus: proficiencyBonus(level) });
}
