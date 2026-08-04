import { NextResponse } from "next/server";
import { campaignState } from "../../../../lib/campaigns";

export const runtime = "nodejs";

export async function GET(_request: Request, { params }: { params: Promise<{ id: string }> }) {
  const state = campaignState((await params).id);
  if (!state) return NextResponse.json({ error: "Unknown campaign" }, { status: 404 });
  return NextResponse.json(state);
}
