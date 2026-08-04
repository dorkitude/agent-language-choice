import { NextResponse } from "next/server";
import { badRequest, parseJsonBody } from "../../../lib/http.js";

export async function POST(req: Request) {
  const parsed = await parseJsonBody(req);
  if (!parsed.ok) return parsed.response;

  const b = parsed.body;
  const strength = Number(b.strength);
  const weight = Number(b.weight);

  if (!Number.isFinite(strength) || !Number.isFinite(weight)) {
    return badRequest();
  }

  const capacity = strength * 15;

  return NextResponse.json({
    capacity,
    weight,
    encumbered: weight > capacity,
  });
}
