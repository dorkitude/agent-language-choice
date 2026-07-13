import { NextResponse } from "next/server";
import { resetStorage, SCHEMA_VERSION } from "../../db";

export async function POST() {
  resetStorage();
  return NextResponse.json({ ok: true, schema_version: SCHEMA_VERSION });
}
