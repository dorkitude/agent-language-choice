import type { ServerResponse } from 'node:http';
import { sendJson } from '../http.js';
import { initializeSchema, isDbInitialized, resetSchema, SCHEMA_VERSION } from '../db.js';

export function handleStorageStatus(res: ServerResponse): boolean {
  sendJson(res, 200, { driver: 'sqlite', schema_version: SCHEMA_VERSION, initialized: isDbInitialized() });
  return true;
}

export function handleStorageReset(res: ServerResponse): boolean {
  resetSchema();
  sendJson(res, 200, { ok: true, schema_version: SCHEMA_VERSION });
  return true;
}
