import { NextResponse } from "next/server";
import { getCampaignAudit } from "../../../../lib/storage.js";
import { notFound } from "../../../../lib/http.js";

export const dynamic = "force-dynamic";

export async function GET(
  _req: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;

  const audit = getCampaignAudit(id);
  if (!audit) {
    return notFound();
  }

  return NextResponse.json(audit);
}
