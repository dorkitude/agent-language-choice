import { NextResponse } from "next/server";

export async function POST(request: Request) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "invalid JSON" }, { status: 400 });
  }

  const { roll, modifier, dc } = (body ?? {}) as {
    roll?: unknown;
    modifier?: unknown;
    dc?: unknown;
  };

  if (typeof roll !== "number" || typeof modifier !== "number" || typeof dc !== "number") {
    return NextResponse.json({ error: "roll, modifier, and dc must be numbers" }, { status: 400 });
  }

  const total = roll + modifier;
  const success = total >= dc;
  const margin = total - dc;

  return NextResponse.json({ total, success, margin });
}
