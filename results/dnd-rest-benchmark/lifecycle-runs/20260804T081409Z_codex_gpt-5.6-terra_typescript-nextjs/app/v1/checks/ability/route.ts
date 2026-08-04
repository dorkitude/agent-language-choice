import { NextResponse } from "next/server";
import { badRequest, isInteger, isRecord, jsonBody } from "../../../lib/http";

export async function POST(request: Request) {
  const body = await jsonBody(request);
  if (!isRecord(body) || !isInteger(body.roll) || !isInteger(body.modifier) || !isInteger(body.dc)) {
    return badRequest();
  }

  const total = body.roll + body.modifier;
  return NextResponse.json({
    total,
    success: total >= body.dc,
    margin: total - body.dc,
  });
}
