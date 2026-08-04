import { NextResponse } from "next/server";
import { SCHEMA_VERSION, storageInitialized } from "../../../lib/storage";

export const runtime = "nodejs";

export function GET() {
  return NextResponse.json({ driver: "sqlite", schema_version: SCHEMA_VERSION, initialized: storageInitialized() });
}
