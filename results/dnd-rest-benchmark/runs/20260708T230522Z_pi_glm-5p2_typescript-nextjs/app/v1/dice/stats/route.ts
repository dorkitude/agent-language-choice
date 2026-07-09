import { NextResponse } from 'next/server';

export const dynamic = 'force-dynamic';

// <count>d<sides>[+<modifier>|-<modifier>]
// count and sides must be positive base-10 integers (no leading zeros).
const EXPR_RE = /^([1-9][0-9]*)d([1-9][0-9]*)(?:([+-])([0-9]+))?$/;

export async function POST(request: Request) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: 'invalid json' }, { status: 400 });
  }

  const expression = (body as { expression?: unknown } | null)?.expression;
  if (typeof expression !== 'string') {
    return NextResponse.json({ error: 'invalid expression' }, { status: 400 });
  }

  const m = expression.match(EXPR_RE);
  if (!m) {
    return NextResponse.json({ error: 'invalid expression' }, { status: 400 });
  }

  const dice_count = parseInt(m[1]!, 10);
  const sides = parseInt(m[2]!, 10);
  let modifier = 0;
  if (m[3] !== undefined) {
    modifier = parseInt(m[4]!, 10);
    if (m[3] === '-') modifier = -modifier;
  }

  const min = dice_count + modifier;
  const max = dice_count * sides + modifier;
  const average = (min + max) / 2;

  return NextResponse.json({ dice_count, sides, modifier, min, max, average });
}
