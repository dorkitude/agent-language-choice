import { NextResponse } from "next/server";

export async function POST(request: Request) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "invalid json" }, { status: 400 });
  }

  const score = (body as { score?: unknown } | null)?.score;

  if (
    typeof score !== "number" ||
    !Number.isInteger(score) ||
    score < 1 ||
    score > 30
  ) {
    return NextResponse.json({ error: "invalid score" }, { status: 400 });
  }

  const modifier = Math.floor((score - 10) / 2);
  return NextResponse.json({ score, modifier });
}
