import { resetStorage, SCHEMA_VERSION } from "../../db.js";

export async function POST() {
  resetStorage();
  return Response.json({ ok: true, schema_version: SCHEMA_VERSION });
}
