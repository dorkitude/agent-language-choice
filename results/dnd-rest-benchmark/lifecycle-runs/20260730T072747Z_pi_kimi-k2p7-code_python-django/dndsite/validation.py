"""Small request parsing helpers."""

import json


def _parse_json_body(request):
    """Parse the request body as JSON. Return None on any failure."""
    try:
        return json.loads(request.body)
    except Exception:
        return None
