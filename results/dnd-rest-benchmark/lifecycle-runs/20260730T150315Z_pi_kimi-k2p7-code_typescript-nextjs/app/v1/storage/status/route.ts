import { NextResponse } from "next/server";
import { getDb, isStorageInitialized } from "../../../lib/storage.js";

export const dynamic = "force-dynamic";

export async function GET() {
  const row = getDb()
    .prepare("SELECT version FROM schema_version")
    .get() as { version: number } | undefined;

  return NextResponse.json({
    driver: "sqlite",
    schema_version: row?.version ?? 1,
    initialized: isStorageInitialized(),
  });
}
