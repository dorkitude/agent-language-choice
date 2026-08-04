import { NextResponse } from 'next/server';

export const dynamic = 'force-dynamic';

interface AbilityRequest {
  roll: number;
  modifier: number;
  dc: number;
}

export async function POST(request: Request) {
  let body: Partial<AbilityRequest>;
  try {
    body = (await request.json()) as Partial<AbilityRequest>;
  } catch {
    return NextResponse.json({ error: 'Invalid JSON' }, { status: 400 });
  }

  const roll = Number(body?.roll);
  const modifier = Number(body?.modifier);
  const dc = Number(body?.dc);

  if (!Number.isFinite(roll) || !Number.isFinite(modifier) || !Number.isFinite(dc)) {
    return NextResponse.json({ error: 'Invalid request' }, { status: 400 });
  }

  const total = roll + modifier;
  const success = total >= dc;
  const margin = total - dc;

  return NextResponse.json({ total, success, margin });
}
