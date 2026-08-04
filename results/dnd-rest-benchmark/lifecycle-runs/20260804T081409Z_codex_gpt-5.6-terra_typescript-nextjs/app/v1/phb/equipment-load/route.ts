import { NextResponse } from "next/server";
import { badRequest, isInteger, isRecord, jsonBody } from "../../../lib/http";

export async function POST(request: Request) {
  const body = await jsonBody(request);
  if (
    !isRecord(body) ||
    !isInteger(body.strength) || body.strength < 0 ||
    !isInteger(body.weight) || body.weight < 0
  ) {
    return badRequest();
  }

  const capacity = body.strength * 15;
  return NextResponse.json({
    capacity,
    weight: body.weight,
    encumbered: body.weight > capacity,
  });
}
