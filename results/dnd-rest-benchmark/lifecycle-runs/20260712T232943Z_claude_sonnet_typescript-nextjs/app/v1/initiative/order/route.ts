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
    return Response.json({ error: "invalid JSON" }, { status: 400 });
  }

  if (typeof body !== "object" || body === null || !Array.isArray((body as Record<string, unknown>).combatants)) {
    return Response.json({ error: "combatants array is required" }, { status: 400 });
  }

  const combatants = (body as Record<string, unknown>).combatants as Combatant[];

  const scored = combatants.map((combatant) => ({
    name: combatant.name,
    dex: combatant.dex,
    score: combatant.roll + combatant.dex,
  }));

  scored.sort((a, b) => {
    if (b.score !== a.score) return b.score - a.score;
    if (b.dex !== a.dex) return b.dex - a.dex;
    return a.name < b.name ? -1 : a.name > b.name ? 1 : 0;
  });

  return Response.json({
    order: scored.map(({ name, score }) => ({ name, score })),
  });
}
