"""Flask Blueprint for the D&D DM Tools API.

The `api` Blueprint is defined here and then populated by the domain
modules imported below. This keeps the route surface in one logical
namespace while splitting the implementation into maintainable pieces.
"""

from flask import Blueprint

api = Blueprint("api", __name__)

from . import _common  # noqa: F401
from . import core, campaigns, play, dm  # noqa: F401
