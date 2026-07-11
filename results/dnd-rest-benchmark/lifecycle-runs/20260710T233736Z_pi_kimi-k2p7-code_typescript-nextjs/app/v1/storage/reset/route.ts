import { resetDatabase, storageStatus } from "../../../lib/db.js";

export async function POST() {
  resetDatabase();
  return Response.json({ ok: true, schema_version: storageStatus().schema_version });
}
