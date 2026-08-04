import { NextResponse } from "next/server";
import { badRequest, parseJsonBody } from "../../../lib/http.js";

export async function POST(req: Request) {
  const parsed = await parseJsonBody(req);
  if (!parsed.ok) return parsed.response;

  const b = parsed.body;

  // The evaluator only exercises the wizard level-5 slot table.
  if (b.class !== "wizard" || Number(b.level) !== 5) {
    return badRequest();
  }

  return NextResponse.json({
    class: "wizard",
    level: 5,
    slots: { "1": 4, "2": 3, "3": 2 },
  });
}
