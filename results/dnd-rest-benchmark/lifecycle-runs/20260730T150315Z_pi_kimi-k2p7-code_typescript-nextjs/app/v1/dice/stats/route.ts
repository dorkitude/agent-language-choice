import { NextResponse } from "next/server";
import { parseDiceStats } from "../../../lib/engine.js";
import { badRequest, parseJsonBody } from "../../../lib/http.js";

export async function POST(req: Request) {
  const parsed = await parseJsonBody(req);
  if (!parsed.ok) return parsed.response;

  const expression = parsed.body.expression;
  if (typeof expression !== "string") {
    return badRequest();
  }

  const result = parseDiceStats(expression);
  if (!result) {
    return NextResponse.json({ error: "Invalid expression" }, { status: 400 });
  }

  return NextResponse.json(result);
}
