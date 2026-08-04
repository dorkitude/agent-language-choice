export function sendJson(res, status, body) {
  const payload = JSON.stringify(body);
  res.writeHead(status, { 'Content-Type': 'application/json' });
  res.end(payload);
}

export function readBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    req.on('data', (c) => chunks.push(c));
    req.on('end', () => resolve(Buffer.concat(chunks).toString('utf8')));
    req.on('error', reject);
  });
}

// Reads and JSON-parses the request body. On malformed JSON it writes the
// 400 response itself and returns { ok: false } so callers can `return`
// immediately without duplicating the try/catch at every route.
export async function parseJsonBody(req, res) {
  const raw = await readBody(req);
  try {
    return { ok: true, data: JSON.parse(raw) };
  } catch {
    sendJson(res, 400, { error: 'invalid JSON' });
    return { ok: false, data: undefined };
  }
}
