"""Entry point for the D&D DM Tools Flask API."""

import os

from flask import Flask

import storage
from routes import api

app = Flask(__name__)
app.register_blueprint(api)

# Resetting the database on startup preserves the prior checkpoint behavior:
# every server process starts with a clean, fully initialized schema.
storage.reset_db()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ["PORT"]))
