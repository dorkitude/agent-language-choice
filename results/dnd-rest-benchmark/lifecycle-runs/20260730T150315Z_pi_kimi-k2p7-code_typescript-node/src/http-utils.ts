import { IncomingMessage, ServerResponse } from 'node:http';

/** Write a JSON response with the given status and object. */
export function sendJSON(res: ServerResponse, status: number, body: unknown): void {
  res.writeHead(status, { 'Content-Type': 'application/json' });
  res.end(JSON.stringify(body));
}

/** Read the raw request body as UTF-8. */
export async function readBody(req: IncomingMessage): Promise<string> {
  const chunks: Buffer[] = [];
  for await (const chunk of req) {
    chunks.push(chunk as Buffer);
  }
  return Buffer.concat(chunks).toString('utf8');
}

/**
 * Parse the request body as JSON. Returns `{}` for an empty body and throws on
 * invalid JSON so the caller can respond with a 400 error.
 */
export async function parseJSONBody(req: IncomingMessage): Promise<unknown> {
  const raw = await readBody(req);
  if (!raw) return {};
  try {
    return JSON.parse(raw);
  } catch {
    throw new Error('invalid json');
  }
}
