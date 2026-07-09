type Combatant = {
  name?: unknown;
  dex?: unknown;
  roll?: unknown;
};

type InitiativeRequest = {
  combatants?: unknown;
};

function badRequest() {
  return Response.json({ error: "bad_request" }, { status: 400 });
}

function isNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

export async function POST(request: Request) {
  let body: InitiativeRequest;

  try {
    body = await request.json();
  } catch {
    return badRequest();
  }

  if (!Array.isArray(body.combatants)) {
    return badRequest();
  }

  const combatants = body.combatants as Combatant[];
  const scored = combatants.map((combatant) => {
    if (
      combatant === null ||
      typeof combatant !== "object" ||
      typeof combatant.name !== "string" ||
      !isNumber(combatant.dex) ||
      !isNumber(combatant.roll)
    ) {
      return null;
    }

    return {
      name: combatant.name,
      dex: combatant.dex,
      score: combatant.roll + combatant.dex,
    };
  });

  if (scored.some((combatant) => combatant === null)) {
    return badRequest();
  }

  scored.sort((a, b) => {
    if (a === null || b === null) return 0;
    return b.score - a.score || b.dex - a.dex || a.name.localeCompare(b.name);
  });

  return Response.json({
    order: scored.map((combatant) => ({
      name: combatant?.name,
      score: combatant?.score,
    })),
  });
}
