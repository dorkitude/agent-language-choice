export function readBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    req.on('data', chunk => chunks.push(chunk));
    req.on('end', () => {
      try {
        resolve(Buffer.concat(chunks).toString('utf8'));
      } catch (err) {
        reject(err);
      }
    });
    req.on('error', reject);
  });
}

export function sendJson(res, status, body) {
  const data = JSON.stringify(body);
  res.writeHead(status, {
    'Content-Type': 'application/json',
    'Content-Length': Buffer.byteLength(data),
  });
  res.end(data);
}

export function badRequest(res, message) {
  sendJson(res, 400, { error: message });
}

export function unauthorized(res, message) {
  sendJson(res, 401, { error: message });
}

export function forbidden(res, message) {
  sendJson(res, 403, { error: message });
}

export function notFound(res) {
  sendJson(res, 404, { error: 'not found' });
}

export function methodNotAllowed(res) {
  sendJson(res, 405, { error: 'method not allowed' });
}

export function conflict(res, message) {
  sendJson(res, 409, { error: message });
}

export function parseJson(body) {
  try {
    return JSON.parse(body);
  } catch {
    return undefined;
  }
}
