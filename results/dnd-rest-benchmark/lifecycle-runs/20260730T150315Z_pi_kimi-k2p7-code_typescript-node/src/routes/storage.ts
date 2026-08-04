import { ServerResponse } from 'node:http';
import { resetDatabase, SCHEMA_VERSION, isInitialized } from '../db.js';
import { sendJSON } from '../http-utils.js';

export function storageStatus(res: ServerResponse): void {
  sendJSON(res, 200, {
    driver: 'sqlite',
    schema_version: SCHEMA_VERSION,
    initialized: isInitialized(),
  });
}

export function storageReset(res: ServerResponse): void {
  resetDatabase();
  sendJSON(res, 200, { ok: true, schema_version: SCHEMA_VERSION });
}
