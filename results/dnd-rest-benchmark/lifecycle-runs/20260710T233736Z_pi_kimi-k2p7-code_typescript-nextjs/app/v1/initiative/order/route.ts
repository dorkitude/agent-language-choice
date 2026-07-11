interface Combatant {
  name: string;
  dex: number;
  roll: number;
}

export async function POST(request: Request) {
  const body = await request.json();
  const combatants: Combatant[] = body.combatants ?? [];

  const order = combatants
    .map((c) => ({ name: c.name, score: c.roll + c.dex, dex: c.dex }))
    .sort((a, b) => {
      if (b.score !== a.score) return b.score - a.score;
      if (b.dex !== a.dex) return b.dex - a.dex;
      return a.name.localeCompare(b.name);
    })
    .map(({ name, score }) => ({ name, score }));

  return Response.json({ order });
}
