import { NextResponse } from 'next/server';

// Grammar: <count>d<sides>[+<modifier>|-<modifier>]
// count and sides must be positive base-10 integers; modifier defaults to 0.
const DICE_RE = /^([0-9]+)d([0-9]+)(?:([+-])([0-9]+))?$/;

export async function POST(request: Request) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: 'invalid json' }, { status: 400 });
  }

  const expression = (body as { expression?: unknown })?.expression;
  if (typeof expression !== 'string') {
    return NextResponse.json({ error: 'invalid expression' }, { status: 400 });
  }

  const match = expression.trim().match(DICE_RE);
  if (!match) {
    return NextResponse.json({ error: 'invalid expression' }, { status: 400 });
  }

  const count = parseInt(match[1], 10);
  const sides = parseInt(match[2], 10);
  if (count <= 0 || sides <= 0) {
    return NextResponse.json({ error: 'invalid expression' }, { status: 400 });
  }

  let modifier = 0;
  if (match[3] !== undefined && match[4] !== undefined) {
    modifier = parseInt(match[4], 10);
    if (match[3] === '-') modifier = -modifier;
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
