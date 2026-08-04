"""Entry point for the D&D DM Tools HTTP server.

Imports the request handler from `api` and starts the stdlib HTTP server on
127.0.0.1 using the PORT environment variable (default 8080).
"""

import os
from http.server import HTTPServer

from api import Handler

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    server = HTTPServer(("127.0.0.1", port), Handler)
    server.serve_forever()
