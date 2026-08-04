import { NextResponse } from "next/server";
import { badRequest, notFound, parseJsonBody } from "../../../../../lib/http.js";
import { getCampaignRiskReport } from "../../../../../lib/storage.js";

export const dynamic = "force-dynamic";

export async function POST(
  req: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;

  const parsed = await parseJsonBody(req);
  if (!parsed.ok) return parsed.response;

  if (typeof parsed.body.include_zeroes !== "boolean") {
    return badRequest();
  }

  const report = getCampaignRiskReport(id);
  if (!report) {
    return notFound();
  }

  return NextResponse.json(report);
}
