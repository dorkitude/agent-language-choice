import { NextResponse } from "next/server";
import { getCampaign, hasEvent, insertEvent } from "../../store";

export async function POST(
  req: Request,
  ctx: { params: Promise<{ id: string }> }
) {
  const { id: campaignId } = await ctx.params;

  if (!getCampaign(campaignId)) {
    return NextResponse.json({ error: "unknown campaign" }, { status: 404 });
  }

  let body: unknown;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "invalid json" }, { status: 400 });
  }

  const obj =
    typeof body === "object" && body !== null
      ? (body as Record<string, unknown>)
      : {};
  const id = obj.id;
  const kind = obj.kind;
  const summary = obj.summary;

  if (typeof id !== "string" || id.length === 0) {
    return NextResponse.json({ error: "invalid id" }, { status: 400 });
  }
  if (typeof kind !== "string" || kind.length === 0) {
    return NextResponse.json({ error: "invalid kind" }, { status: 400 });
  }
  if (typeof summary !== "string" || summary.length === 0) {
    return NextResponse.json({ error: "invalid summary" }, { status: 400 });
  }

  if (hasEvent(campaignId, id)) {
    return NextResponse.json({ error: "duplicate id" }, { status: 409 });
  }

  insertEvent(campaignId, { id, kind, summary });
  return NextResponse.json({ id, kind }, { status: 201 });
}
