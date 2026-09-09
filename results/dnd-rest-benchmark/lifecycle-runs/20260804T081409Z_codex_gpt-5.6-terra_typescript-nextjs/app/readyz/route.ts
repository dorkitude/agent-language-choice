import { NextResponse } from "next/server";
import { isMaintenanceMode } from "../lib/service-mode";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export function GET() {
  if (isMaintenanceMode()) {
    return NextResponse.json({ status: "maintenance", schema_version: 2 }, { status: 503 });
  }
  return NextResponse.json({ status: "ready", schema_version: 2 });
}
