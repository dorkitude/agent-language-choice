import type { ServerResponse } from 'node:http';
import { sendJson } from '../http.js';

export function handleHealth(res: ServerResponse): boolean {
  sendJson(res, 200, { ok: true });
  return true;
}
