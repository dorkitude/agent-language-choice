import { NextResponse } from "next/server";
import { getDb, isInitialized, SCHEMA_VERSION } from "../../db";

export async function GET() {
  const db = getDb();
  return NextResponse.json({
    driver: "sqlite",
    schema_version: SCHEMA_VERSION,
    initialized: isInitialized(db),
  });
}
