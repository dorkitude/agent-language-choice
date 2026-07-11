import { NextResponse } from 'next/server';

function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

export async function POST(request: Request) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: 'invalid json' }, { status: 400 });
  }

  const { roll, modifier, dc } = (body ?? {}) as {
    roll?: unknown;
    modifier?: unknown;
    dc?: unknown;
  };

  if (!isFiniteNumber(roll) || !isFiniteNumber(modifier) || !isFiniteNumber(dc)) {
    return NextResponse.json({ error: 'invalid input' }, { status: 400 });
  }

  const total = roll + modifier;
  const success = total >= dc;
  const margin = total - dc;

  return NextResponse.json({ total, success, margin });
}
