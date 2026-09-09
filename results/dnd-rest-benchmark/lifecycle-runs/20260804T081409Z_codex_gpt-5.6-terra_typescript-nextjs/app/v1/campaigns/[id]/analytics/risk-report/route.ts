import { NextResponse } from "next/server";
import { campaignAnalytics, getCampaign } from "../../../../../lib/campaigns";
import { badRequest, isRecord, jsonBody } from "../../../../../lib/http";

export const runtime = "nodejs";

const signalNames = ["has_dm", "has_characters", "has_next_session", "has_active_quest"] as const;

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const body = await jsonBody(request);
  if (!isRecord(body) || (body.include_zeroes !== undefined && typeof body.include_zeroes !== "boolean")) {
    return badRequest();
  }

  const campaignId = (await params).id;
  if (!getCampaign(campaignId)) return NextResponse.json({ error: "Unknown campaign" }, { status: 404 });

  const { signals } = campaignAnalytics(campaignId);
  const missing = signalNames.filter((signal) => !signals[signal]).map((signal) => signal.replace(/^has_/, ""));
  const risk_level = missing.length === 0 ? "low" : missing.length <= 2 ? "medium" : "high";
  const reportedSignals = body.include_zeroes
    ? signals
    : Object.fromEntries(signalNames.filter((signal) => signals[signal]).map((signal) => [signal, true]));

  return NextResponse.json({ campaign_id: campaignId, risk_level, missing, signals: reportedSignals });
}
