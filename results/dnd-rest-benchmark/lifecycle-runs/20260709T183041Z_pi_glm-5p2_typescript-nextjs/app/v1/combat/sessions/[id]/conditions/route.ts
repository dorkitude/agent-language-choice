import { NextResponse } from 'next/server';
import { getSession, type Condition } from '../../../state';

export const dynamic = 'force-dynamic';

interface Context {
  params: Promise<{ id: string }>;
}

export async function POST(request: Request, { params }: Context) {
  const { id } = await params;
  const session = getSession(id);
  if (!session) {
    return NextResponse.json({ error: 'unknown session' }, { status: 404 });
  }

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: 'invalid json' }, { status: 400 });
  }

  const target = (body as { target?: unknown })?.target;
  const condition = (body as { condition?: unknown })?.condition;
  const duration = (body as { duration_rounds?: unknown })?.duration_rounds;

  if (
    typeof target !== 'string' ||
    target.length === 0 ||
    !session.order.some((c) => c.name === target)
  ) {
    return NextResponse.json({ error: 'invalid target' }, { status: 400 });
  }

  if (typeof condition !== 'string' || condition.length === 0) {
    return NextResponse.json({ error: 'invalid condition' }, { status: 400 });
  }

  if (
    typeof duration !== 'number' ||
    !Number.isInteger(duration) ||
    duration <= 0
  ) {
    return NextResponse.json(
      { error: 'invalid duration_rounds' },
      { status: 400 },
    );
  }

  const list: Condition[] = session.conditions[target] ?? [];
  list.push({ condition, remaining_rounds: duration });
  session.conditions[target] = list;

  return NextResponse.json({
    target,
    conditions: list.map((c) => ({
      condition: c.condition,
      remaining_rounds: c.remaining_rounds,
    })),
  });
}
