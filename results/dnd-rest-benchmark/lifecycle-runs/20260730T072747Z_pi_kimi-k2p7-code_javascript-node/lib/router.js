import { readBody, methodNotAllowed, notFound } from './http.js';

// A tiny HTTP router. Routes are registered with .get() / .post() / .put() and
// matched in registration order. The first route with a matching method and URL
// wins, and its captured path segments are passed to the handler as positional
// arguments.
//
// Routing preserves the original behavior of the cumulative evaluator suite:
//   - GET/DELETE or any method other than POST/PUT without a match -> 405
//     Method Not Allowed (body is not read)
//   - POST or PUT without a match -> body is read, then 404 Not Found
//   - POST or PUT with a match -> body is read, then the handler runs
export function createRouter() {
  const routes = [];

  function add(method, pattern, handler) {
    routes.push({ method, pattern, handler });
    return router;
  }

  async function handle(req, res) {
    const { method, url } = req;
    const readsBody = method === 'POST' || method === 'PUT';

    for (const route of routes) {
      if (route.method !== method) continue;
      const match = url.match(route.pattern);
      if (match) {
        if (readsBody) {
          req.body = await readBody(req);
        }
        // Spread captured groups so handlers receive each path segment as a
        // separate positional argument (e.g., id, slug, campaignId).
        return route.handler(req, res, ...match.slice(1));
      }
    }

    if (!readsBody) {
      return methodNotAllowed(res);
    }

    req.body = await readBody(req);
    return notFound(res);
  }

  const router = {
    get: (pattern, handler) => add('GET', pattern, handler),
    post: (pattern, handler) => add('POST', pattern, handler),
    put: (pattern, handler) => add('PUT', pattern, handler),
    delete: (pattern, handler) => add('DELETE', pattern, handler),
    handle,
  };

  return router;
}
