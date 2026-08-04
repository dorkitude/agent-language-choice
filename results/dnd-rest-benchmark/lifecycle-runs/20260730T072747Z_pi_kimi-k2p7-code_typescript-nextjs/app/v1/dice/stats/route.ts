import { NextResponse } from 'next/server';

export const dynamic = 'force-dynamic';

interface DiceRequest {
  expression: string;
}

export async function POST(request: Request) {
  let body: DiceRequest;
  try {
    body = (await request.json()) as DiceRequest;
  } catch {
    return NextResponse.json({ error: 'Invalid JSON' }, { status: 400 });
  }

  const expression = typeof body?.expression === 'string' ? body.expression.trim() : '';
  const match = expression.match(/^(\d+)d(\d+)([+-]\d+)?$/);
  if (!match) {
    return NextResponse.json({ error: 'Invalid expression' }, { status: 400 });
  }

  const diceCount = parseInt(match[1], 10);
  const sides = parseInt(match[2], 10);
  const modifier = match[3] ? parseInt(match[3], 10) : 0;

  if (diceCount <= 0 || sides <= 0) {
    return NextResponse.json({ error: 'Invalid expression' }, { status: 400 });
  }

  const min = diceCount + modifier;
  const max = diceCount * sides + modifier;
  const average = (min + max) / 2;

  return NextResponse.json({
    dice_count: diceCount,
    sides,
    modifier,
    min,
    max,
    average,
  });
}
