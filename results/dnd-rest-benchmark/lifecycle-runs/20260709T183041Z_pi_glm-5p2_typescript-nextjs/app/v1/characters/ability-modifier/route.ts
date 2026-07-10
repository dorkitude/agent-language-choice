import { NextResponse } from 'next/server';
import { abilityModifier, isValidScore } from '../rules';

export async function POST(request: Request) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: 'invalid json' }, { status: 400 });
  }

  const score = (body as { score?: unknown })?.score;
  if (!isValidScore(score)) {
    return NextResponse.json({ error: 'invalid score' }, { status: 400 });
  }

  return NextResponse.json({ score, modifier: abilityModifier(score) });
}
