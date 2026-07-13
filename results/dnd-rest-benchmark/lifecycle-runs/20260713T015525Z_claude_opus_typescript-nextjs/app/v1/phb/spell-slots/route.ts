import { NextResponse } from "next/server";

const SLOTS: Record<string, Record<number, Record<string, number>>> = {
  wizard: {
    5: { "1": 4, "2": 3, "3": 2 },
  },
};

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
  const cls = obj.class;
  const level = obj.level;

  if (typeof cls !== "string" || typeof level !== "number") {
    return NextResponse.json({ error: "invalid request" }, { status: 400 });
  }

  const byClass = SLOTS[cls];
  const slots = byClass ? byClass[level] : undefined;
  if (!slots) {
    return NextResponse.json(
      { error: "unsupported class or level" },
      { status: 400 },
    );
  }

  return NextResponse.json({ class: cls, level, slots });
}
