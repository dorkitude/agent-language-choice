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
  const score = obj.score;

  if (
    typeof score !== "number" ||
    !Number.isInteger(score) ||
    score < 1 ||
    score > 30
  ) {
    return NextResponse.json({ error: "invalid request" }, { status: 400 });
  }

  const modifier = Math.floor((score - 10) / 2);
  return NextResponse.json({ score, modifier });
}
