import { NextResponse } from "next/server";
import { getCampaignState } from "../../../../lib/storage.js";
import { notFound } from "../../../../lib/http.js";

export const dynamic = "force-dynamic";

export async function GET(
  _req: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;

  const state = getCampaignState(id);
  if (!state) {
    return notFound();
  }

  return NextResponse.json(state);
}
