import { NextResponse } from "next/server";
import { getMonster } from "../../../../lib/compendium";

export const runtime = "nodejs";

export async function GET(_request: Request, { params }: { params: Promise<{ slug: string }> }) {
  const monster = getMonster((await params).slug);
  if (!monster) return NextResponse.json({ error: "Unknown monster" }, { status: 404 });
  return NextResponse.json(monster);
}
