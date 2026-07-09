import { NextResponse } from 'next/server';

export const dynamic = 'force-dynamic';

function isFiniteNumber(x: unknown): x is number {
  return typeof x === 'number' && Number.isFinite(x);
}

export async function POST(request: Request) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: 'invalid json' }, { status: 400 });
  }

  const b = body as { roll?: unknown; modifier?: unknown; dc?: unknown };
  if (!isFiniteNumber(b.roll) || !isFiniteNumber(b.modifier) || !isFiniteNumber(b.dc)) {
    return NextResponse.json({ error: 'invalid input' }, { status: 400 });
  }

  const total = b.roll + b.modifier;
  const success = total >= b.dc;
  const margin = total - b.dc;

  return NextResponse.json({ total, success, margin });
}
