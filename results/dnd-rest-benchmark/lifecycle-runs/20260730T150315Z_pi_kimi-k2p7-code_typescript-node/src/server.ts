import { createServer } from 'node:http';
import { initializeDatabase } from './db.js';
import { parseJSONBody } from './http-utils.js';
import { handleDelete, handleGet, handlePost, handlePut, sendMethodNotAllowed, sendNotFound } from './router.js';

const PORT = process.env.PORT ? Number(process.env.PORT) : 3000;

initializeDatabase();

/**
 * HTTP server entry point. Dispatches to GET/POST/PUT handlers from the router
 * and falls back to 405/404. The body is read as JSON for mutating methods,
 * with an empty body treated as `{}`.
 */
const server = createServer(async (req, res) => {
  try {
    if (await handleGet(req, res)) return;

    if (req.method !== 'POST' && req.method !== 'PUT' && req.method !== 'DELETE') {
      sendMethodNotAllowed(res);
      return;
    }

    if (req.method === 'DELETE') {
      if (await handleDelete(req, res)) return;
      sendNotFound(res);
      return;
    }

    let body: unknown;
    try {
      body = await parseJSONBody(req);
    } catch {
      res.writeHead(400, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ error: 'invalid json' }));
      return;
    }

    if (req.method === 'POST') {
      if (await handlePost(req, res, body)) return;
    } else {
      if (await handlePut(req, res, body)) return;
    }
    sendNotFound(res);
  } catch (err) {
    res.writeHead(500, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ error: 'internal server error' }));
    console.error(err);
  }
});

server.listen(PORT, '127.0.0.1', () => {
  console.log(`Server listening on 127.0.0.1:${PORT}`);
});
