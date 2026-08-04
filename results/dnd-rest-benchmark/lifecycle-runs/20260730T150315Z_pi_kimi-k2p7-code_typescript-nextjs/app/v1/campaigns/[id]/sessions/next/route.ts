import { NextResponse } from "next/server";
import { getCampaign, getNextSession } from "../../../../../lib/storage.js";
import { notFound } from "../../../../../lib/http.js";

export const dynamic = "force-dynamic";

export async function GET(
  _req: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;

  if (!getCampaign(id)) {
    return notFound();
  }

  const session = getNextSession(id);
  if (!session) {
    return notFound();
  }

  return NextResponse.json(session);
}
