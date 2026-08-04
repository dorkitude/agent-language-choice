import { getDb, isInitialized, SCHEMA_VERSION } from "../../db.js";

export async function GET() {
  getDb();
  return Response.json({
    driver: "sqlite",
    schema_version: SCHEMA_VERSION,
    initialized: isInitialized(),
  });
}
