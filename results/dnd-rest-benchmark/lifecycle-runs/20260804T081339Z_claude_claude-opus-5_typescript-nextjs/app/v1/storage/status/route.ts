import { DRIVER, SCHEMA_VERSION, isInitialized } from "../../../../lib/db";
import { json } from "../../../../lib/http";

export const dynamic = "force-dynamic";

export function GET(): Response {
  return json({
    driver: DRIVER,
    schema_version: SCHEMA_VERSION,
    initialized: isInitialized(),
  });
}
