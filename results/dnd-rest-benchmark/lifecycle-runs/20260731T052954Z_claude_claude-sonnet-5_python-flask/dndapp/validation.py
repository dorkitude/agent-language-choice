"""Shared request-payload validation helpers and patterns.

These are intentionally permissive about *where* a value comes from (JSON
body, path segment) and strict about shape — every route module reuses these
rather than re-implementing ad hoc isinstance() checks.
"""

import re

DICE_RE = re.compile(r"^(\d+)d(\d+)([+-]\d+)?$")
USERNAME_RE = re.compile(r"^[a-z0-9_-]{2,32}$")
SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def valid_int(value):
    """True for real ints, excluding bool (which is an int subclass in Python)."""
    return isinstance(value, int) and not isinstance(value, bool)


def valid_int_in_range(value, lo, hi):
    return valid_int(value) and lo <= value <= hi


def valid_slug(value):
    return isinstance(value, str) and bool(SLUG_RE.match(value))


def valid_nonempty_str(value):
    return isinstance(value, str) and bool(value.strip())
