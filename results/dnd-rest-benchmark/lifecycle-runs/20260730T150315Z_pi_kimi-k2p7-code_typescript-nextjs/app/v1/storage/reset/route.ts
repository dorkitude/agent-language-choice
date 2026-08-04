import { NextResponse } from "next/server";
import { getSchemaVersion, resetStorage } from "../../../lib/storage.js";

export const dynamic = "force-dynamic";

export async function POST() {
  resetStorage();

  return NextResponse.json({
    ok: true,
    schema_version: getSchemaVersion(),
  });
}
