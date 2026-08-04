// Minimal method+path router. Routes are matched in registration order,
// mirroring the original if-chain's semantics (first match wins).
export function createRouter() {
  const routes = [];

  // `pattern` is either a "/foo/:bar/baz" string (":name" segments become
  // capture groups) or a RegExp for routes that need custom matching, such
  // as restricting a segment to a fixed set of literal actions.
  function add(method, pattern, handler, paramNames = []) {
    if (typeof pattern === 'string') {
      const names = [];
      const regexSource = pattern.replace(/:[^/]+/g, (segment) => {
        names.push(segment.slice(1));
        return '([^/]+)';
      });
      routes.push({ method, regex: new RegExp(`^${regexSource}$`), paramNames: names, handler });
    } else {
      routes.push({ method, regex: pattern, paramNames, handler });
    }
  }

  async function dispatch(req, res, pathname) {
    for (const route of routes) {
      if (route.method !== req.method) continue;
      const match = route.regex.exec(pathname);
      if (!match) continue;
      const params = {};
      route.paramNames.forEach((name, i) => {
        params[name] = decodeURIComponent(match[i + 1]);
      });
      await route.handler(req, res, params);
      return true;
    }
    return false;
  }

  return {
    get: (pattern, handler, paramNames) => add('GET', pattern, handler, paramNames),
    post: (pattern, handler, paramNames) => add('POST', pattern, handler, paramNames),
    put: (pattern, handler, paramNames) => add('PUT', pattern, handler, paramNames),
    delete: (pattern, handler, paramNames) => add('DELETE', pattern, handler, paramNames),
    dispatch,
  };
}
