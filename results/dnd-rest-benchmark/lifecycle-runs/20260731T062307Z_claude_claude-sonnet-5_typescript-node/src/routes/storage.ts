// Storage introspection and the destructive full-reset used by the test
// suite between scenarios.
import type { ServerResponse } from "node:http";
import { SCHEMA_VERSION, resetDatabase, storageInitialized } from "../db.js";
import { sendJson } from "../http.js";

export function handleStorageStatus(res: ServerResponse): void {
  sendJson(res, 200, {
    driver: "sqlite",
    schema_version: SCHEMA_VERSION,
    initialized: storageInitialized,
  });
}

export function handleStorageReset(res: ServerResponse): void {
  resetDatabase();
  sendJson(res, 200, { ok: true, schema_version: SCHEMA_VERSION });
}
