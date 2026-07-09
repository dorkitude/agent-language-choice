import { NextResponse } from "next/server";

export async function POST(req: Request) {
  let body: unknown;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "invalid json" }, { status: 400 });
  }

  const { roll, modifier, dc } = (body ?? {}) as {
    roll?: unknown;
    modifier?: unknown;
    dc?: unknown;
  };

  if (
    typeof roll !== "number" ||
    typeof modifier !== "number" ||
    typeof dc !== "number"
  ) {
    return NextResponse.json({ error: "invalid input" }, { status: 400 });
  }

  const total = roll + modifier;
  const success = total >= dc;
  const margin = total - dc;

  return NextResponse.json({ total, success, margin });
}
