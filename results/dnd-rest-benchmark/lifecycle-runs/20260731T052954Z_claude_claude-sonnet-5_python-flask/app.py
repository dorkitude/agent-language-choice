"""Entry point: builds the Flask app, registers routes, and runs the dev server.

See CODEBASE.md for the module map and extension conventions.
"""

import os

from flask import Flask

from dndapp.db import DB_PATH, init_db
from dndapp.routes import register_blueprints

app = Flask(__name__)
register_blueprints(app)

# Each server process starts against a clean database: game.db (and its WAL
# sidecar files) is a runtime artifact, not durable state that should outlive
# a process restart.
for suffix in ("", "-wal", "-shm"):
    path = DB_PATH + suffix
    if os.path.exists(path):
        os.remove(path)
init_db()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ["PORT"]), threaded=True)
