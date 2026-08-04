import { NextResponse } from "next/server";
import { createCampaign } from "../../lib/campaigns";
import { badRequest, isRecord, jsonBody } from "../../lib/http";

export const runtime = "nodejs";

export async function POST(request: Request) {
  const body = await jsonBody(request);
  if (!isRecord(body) || typeof body.id !== "string" || body.id.length === 0 || typeof body.name !== "string" || body.name.length === 0 || typeof body.dm !== "string" || body.dm.length === 0) {
    return badRequest();
  }
  if (!createCampaign({ id: body.id, name: body.name, dm: body.dm })) {
    return NextResponse.json({ error: "Campaign already exists" }, { status: 409 });
  }
  return NextResponse.json({ id: body.id, name: body.name, dm: body.dm }, { status: 201 });
}
