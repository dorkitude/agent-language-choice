import { NextResponse, type NextRequest } from "next/server";

export async function POST(request: NextRequest) {
  let body: { roll?: unknown; modifier?: unknown; dc?: unknown };
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "Invalid JSON" }, { status: 400 });
  }

  const roll = Number(body?.roll);
  const modifier = Number(body?.modifier);
  const dc = Number(body?.dc);

  if (!Number.isInteger(roll) || !Number.isInteger(modifier) || !Number.isInteger(dc)) {
    return NextResponse.json({ error: "Invalid fields" }, { status: 400 });
  }

  const total = roll + modifier;
  const success = total >= dc;
  const margin = total - dc;

  return NextResponse.json({ total, success, margin });
}
