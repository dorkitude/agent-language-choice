import { NextResponse } from "next/server";
import { resetStorage, SCHEMA_VERSION } from "../../../lib/storage";

export const runtime = "nodejs";

export function POST() {
  resetStorage();
  return NextResponse.json({ ok: true, schema_version: SCHEMA_VERSION });
}
