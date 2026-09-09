import { NextResponse } from "next/server";
import { getMaintenanceMode } from "../lib/maintenance.js";

export const dynamic = "force-dynamic";

export async function GET() {
  if (getMaintenanceMode()) {
    return NextResponse.json(
      { status: "maintenance", schema_version: 2 },
      { status: 503 }
    );
  }
  return NextResponse.json({ status: "ready", schema_version: 2 });
}
