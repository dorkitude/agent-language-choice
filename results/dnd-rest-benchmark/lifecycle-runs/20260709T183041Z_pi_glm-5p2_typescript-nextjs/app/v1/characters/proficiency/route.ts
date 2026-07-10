import { NextResponse } from 'next/server';
import { proficiencyBonus, isValidLevel } from '../rules';

export async function POST(request: Request) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: 'invalid json' }, { status: 400 });
  }

  const level = (body as { level?: unknown })?.level;
  if (!isValidLevel(level)) {
    return NextResponse.json({ error: 'invalid level' }, { status: 400 });
  }

  return NextResponse.json({ level, proficiency_bonus: proficiencyBonus(level) });
}
