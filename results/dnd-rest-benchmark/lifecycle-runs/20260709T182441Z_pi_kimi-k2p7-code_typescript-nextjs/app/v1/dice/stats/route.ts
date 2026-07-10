import { NextResponse } from 'next/server';

const DICE_RE = /^(\d+)d(\d+)(?:([+-])(\d+))?$/;

export async function POST(request: Request) {
  let body: { expression?: string };
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: 'Invalid JSON' }, { status: 400 });
  }

  const expression = body?.expression;
  if (typeof expression !== 'string') {
    return NextResponse.json({ error: 'expression required' }, { status: 400 });
  }

  const match = expression.replace(/\s+/g, '').match(DICE_RE);
  if (!match) {
    return NextResponse.json({ error: 'Invalid expression' }, { status: 400 });
  }

  const count = parseInt(match[1], 10);
  const sides = parseInt(match[2], 10);
  const modifier = match[3] ? (match[3] === '+' ? 1 : -1) * parseInt(match[4], 10) : 0;

  if (count <= 0 || sides <= 0) {
    return NextResponse.json({ error: 'count and sides must be positive' }, { status: 400 });
  }

  const min = count + modifier;
  const max = count * sides + modifier;
  const average = Math.round((min + max) / 2);

  return NextResponse.json({
    dice_count: count,
    sides,
    modifier,
    min,
    max,
    average,
  });
}
