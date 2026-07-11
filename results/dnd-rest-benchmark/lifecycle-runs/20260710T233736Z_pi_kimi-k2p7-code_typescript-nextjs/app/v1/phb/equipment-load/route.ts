function validateInteger(value: unknown, name: string): number {
  if (typeof value !== "number" || !Number.isInteger(value)) {
    throw new Error(`${name} must be an integer`);
  }
  return value;
}

export async function POST(request: Request) {
  try {
    const body = await request.json();
    const strength = validateInteger(body.strength, "strength");
    if (strength < 1) {
      throw new Error("strength must be at least 1");
    }
    const weight = validateInteger(body.weight, "weight");
    if (weight < 0) {
      throw new Error("weight must be non-negative");
    }

    const capacity = strength * 15;
    return Response.json({
      capacity,
      weight,
      encumbered: weight > capacity,
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : "invalid request";
    return Response.json({ error: message }, { status: 400 });
  }
}
