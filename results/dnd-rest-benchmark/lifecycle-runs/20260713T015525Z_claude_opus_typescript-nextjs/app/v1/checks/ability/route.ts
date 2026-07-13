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
  const roll = obj.roll;
  const modifier = obj.modifier;
  const dc = obj.dc;

  if (
    typeof roll !== "number" ||
    typeof modifier !== "number" ||
    typeof dc !== "number"
  ) {
    return NextResponse.json({ error: "invalid request" }, { status: 400 });
  }

  const total = roll + modifier;
  return NextResponse.json({
    total,
    success: total >= dc,
    margin: total - dc,
  });
}
