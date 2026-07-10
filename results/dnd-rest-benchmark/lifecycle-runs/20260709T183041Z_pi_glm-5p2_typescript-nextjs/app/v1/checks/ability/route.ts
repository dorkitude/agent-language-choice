import { NextResponse } from 'next/server';

export async function POST(request: Request) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: 'invalid json' }, { status: 400 });
  }

  const { roll, modifier, dc } = (body as Record<string, unknown>) ?? {};
  if (
    typeof roll !== 'number' ||
    typeof modifier !== 'number' ||
    typeof dc !== 'number'
  ) {
    return NextResponse.json({ error: 'invalid request' }, { status: 400 });
  }

  const total = roll + modifier;
  const success = total >= dc;
  const margin = total - dc;

  return NextResponse.json({ total, success, margin });
}
