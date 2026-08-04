// Low-level HTTP utilities used by the request router and handlers.

import type { IncomingMessage, ServerResponse } from 'node:http';

export function readBody(req: IncomingMessage): Promise<string> {
  return new Promise((resolve, reject) => {
    let data = '';
    req.on('data', (chunk) => {
      data += chunk;
    });
    req.on('end', () => resolve(data));
    req.on('error', reject);
  });
}

export function sendJson(res: ServerResponse, status: number, body: unknown): void {
  res.statusCode = status;
  res.setHeader('Content-Type', 'application/json');
  res.end(JSON.stringify(body));
}

// Convenience helper for the standard `{ error: message }` error envelope used
// by every API handler. Using this keeps error response shapes consistent.
export function sendError(res: ServerResponse, status: number, message: string): void {
  sendJson(res, status, { error: message });
}
