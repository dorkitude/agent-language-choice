import { json } from "../../../api.js";
import { resetStorage, SCHEMA_VERSION } from "../db.js";

export const runtime = "nodejs";

export function POST() {
  resetStorage();
  return json({ ok: true, schema_version: SCHEMA_VERSION });
}
