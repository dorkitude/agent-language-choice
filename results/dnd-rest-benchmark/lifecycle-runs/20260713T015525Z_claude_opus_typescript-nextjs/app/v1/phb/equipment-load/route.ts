import { NextResponse } from "next/server";

export async function POST(req: Request) {
  let body: unknown;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "invalid json" }, { status: 400 });
  }

  const obj =
    typeof body === "object" && body !== null
      ? (body as Record<string, unknown>)
      : {};
  const strength = obj.strength;
  const weight = obj.weight;

  if (
    typeof strength !== "number" ||
    !Number.isInteger(strength) ||
    strength < 0 ||
    typeof weight !== "number" ||
    weight < 0
  ) {
    return NextResponse.json({ error: "invalid request" }, { status: 400 });
  }

  const capacity = strength * 15;
  const encumbered = weight > capacity;

  return NextResponse.json({ capacity, weight, encumbered });
}
