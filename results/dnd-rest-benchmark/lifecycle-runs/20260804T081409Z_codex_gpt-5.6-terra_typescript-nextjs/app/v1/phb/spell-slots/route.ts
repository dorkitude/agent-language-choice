import { NextResponse } from "next/server";
import { badRequest, isRecord, jsonBody } from "../../../lib/http";

export async function POST(request: Request) {
  const body = await jsonBody(request);
  if (!isRecord(body) || body.class !== "wizard" || body.level !== 5) {
    return badRequest("Unsupported class or level");
  }

  return NextResponse.json({
    class: "wizard",
    level: 5,
    slots: { "1": 4, "2": 3, "3": 2 },
  });
}
