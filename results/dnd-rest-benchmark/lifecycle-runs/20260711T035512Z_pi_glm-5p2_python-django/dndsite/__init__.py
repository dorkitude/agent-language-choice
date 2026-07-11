"""D&D REST API package.

Importing :mod:`dndsite.storage` here ensures the SQLite schema is initialized
when Django loads the settings module (``dndsite.settings``) at server startup,
before the first request is served.
"""
from . import storage as _storage  # noqa: F401  (side-effect: init schema)
