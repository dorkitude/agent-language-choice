function badRequest(message: string) {
  return Response.json({ error: message }, { status: 400 });
}

interface Combatant {
  name: string;
  dex: number;
  roll: number;
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

  const { combatants } = body as { combatants?: unknown };
  if (!Array.isArray(combatants)) {
    return badRequest("combatants must be an array");
  }

  for (const c of combatants as Combatant[]) {
    if (
      typeof c?.name !== "string" ||
      typeof c?.dex !== "number" ||
      typeof c?.roll !== "number"
    ) {
      return badRequest("invalid combatant entry");
    }
  }

  const scored = (combatants as Combatant[]).map((c) => ({
    name: c.name,
    dex: c.dex,
    score: c.roll + c.dex,
  }));

  scored.sort((a, b) => {
    if (b.score !== a.score) return b.score - a.score;
    if (b.dex !== a.dex) return b.dex - a.dex;
    return a.name.localeCompare(b.name);
  });

  return Response.json({
    order: scored.map((c) => ({ name: c.name, score: c.score })),
  });
}
