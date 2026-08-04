import { ServerResponse } from 'node:http';
import { sendJSON } from '../http-utils.js';

export function health(res: ServerResponse): void {
  sendJSON(res, 200, { ok: true });
}
