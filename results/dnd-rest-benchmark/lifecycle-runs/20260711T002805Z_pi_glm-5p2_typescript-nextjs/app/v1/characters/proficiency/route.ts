import { NextResponse } from 'next/server';

export async function POST(request: Request) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: 'invalid json' }, { status: 400 });
  }

  const level = (body as { level?: unknown })?.level;
  if (
    typeof level !== 'number' ||
    !Number.isInteger(level) ||
    level < 1 ||
    level > 20
  ) {
    return NextResponse.json({ error: 'invalid level' }, { status: 400 });
  }

  // 2 + floor((level - 1) / 4): 1-4 -> 2, 5-8 -> 3, 9-12 -> 4, 13-16 -> 5, 17-20 -> 6.
  const proficiency_bonus = 2 + Math.floor((level - 1) / 4);
  return NextResponse.json({ level, proficiency_bonus });
}
