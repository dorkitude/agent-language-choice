import { NextResponse } from 'next/server';

// Grammar: <count>d<sides>[+<modifier>|-<modifier>]
const RE = /^(\d+)d(\d+)(?:([+-])(\d+))?$/;

export async function POST(request: Request) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: 'invalid json' }, { status: 400 });
  }

  const expr = (body as { expression?: unknown })?.expression;
  if (typeof expr !== 'string') {
    return NextResponse.json({ error: 'invalid expression' }, { status: 400 });
  }

  const m = expr.match(RE);
  if (!m) {
    return NextResponse.json({ error: 'invalid expression' }, { status: 400 });
  }

  const count = parseInt(m[1], 10);
  const sides = parseInt(m[2], 10);
  // count and sides must be positive
  if (count <= 0 || sides <= 0) {
    return NextResponse.json({ error: 'invalid expression' }, { status: 400 });
  }

  let modifier = 0;
  if (m[3] !== undefined) {
    const val = parseInt(m[4], 10);
    modifier = m[3] === '-' ? -val : val;
  }

  const min = count + modifier;
  const max = count * sides + modifier;
  const average = (min + max) / 2;

  return NextResponse.json({
    dice_count: count,
    sides,
    modifier,
    min,
    max,
    average,
  });
}
