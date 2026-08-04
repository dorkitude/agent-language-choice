import { SCHEMA_VERSION, resetSchema } from "../../../../lib/db";
import { json } from "../../../../lib/http";

export const dynamic = "force-dynamic";

export function POST(): Response {
  resetSchema();
  return json({ ok: true, schema_version: SCHEMA_VERSION });
}
