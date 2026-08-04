import { NextResponse } from "next/server";
import { getItem } from "../../../../lib/compendium";

export const runtime = "nodejs";

export async function GET(_request: Request, { params }: { params: Promise<{ slug: string }> }) {
  const item = getItem((await params).slug);
  if (!item) return NextResponse.json({ error: "Unknown item" }, { status: 404 });
  return NextResponse.json(item);
}
