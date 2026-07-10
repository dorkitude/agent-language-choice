import { NextResponse } from 'next/server';

export async function POST(request: Request) {
  let body: { roll?: number; modifier?: number; dc?: number };
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: 'Invalid JSON' }, { status: 400 });
  }

  const { roll, modifier, dc } = body;
  if (typeof roll !== 'number' || typeof modifier !== 'number' || typeof dc !== 'number') {
    return NextResponse.json({ error: 'roll, modifier, and dc required' }, { status: 400 });
  }

  const total = roll + modifier;
  const margin = total - dc;
  const success = total >= dc;

  return NextResponse.json({ total, success, margin });
}
