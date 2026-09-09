"""Public readiness/liveness and DM-controlled maintenance switch views."""

import threading

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from ..db import db_conn
from ..http import bad_request, not_found, require_method
from .common import require_actor

# Process-global maintenance switch.  Protected by a lightweight lock so
# concurrent service-mode toggles remain deterministic.
_maintenance_lock = threading.Lock()
_maintenance_mode = False


def _set_maintenance(value):
    """Atomically set the global maintenance mode and return the new value."""
    global _maintenance_mode
    with _maintenance_lock:
        _maintenance_mode = bool(value)
        return _maintenance_mode


def _is_maintenance():
    """Return the current global maintenance mode."""
    with _maintenance_lock:
        return _maintenance_mode


@csrf_exempt
def healthz(request):
    """Public liveness probe; maintenance mode must not affect this."""
    bad = require_method(request, "GET")
    if bad:
        return bad
    return JsonResponse({"status": "ok"})


@csrf_exempt
def readyz(request):
    """Public readiness probe; reports maintenance state when enabled."""
    bad = require_method(request, "GET")
    if bad:
        return bad

    if _is_maintenance():
        return JsonResponse({"status": "maintenance", "schema_version": 2}, status=503)
    return JsonResponse({"status": "ready", "schema_version": 2})


@csrf_exempt
def service_mode(request, id):
    """DM-only toggle for the process-global maintenance switch."""
    bad = require_method(request, "POST")
    if bad:
        return bad

    actor, err = require_actor(request, "dm")
    if err is not None:
        return err

    with db_conn() as conn:
        campaign = conn.execute(
            "SELECT id FROM play_campaigns WHERE id = ?", (id,)
        ).fetchone()
    if campaign is None:
        return not_found("campaign not found")

    body = require_service_mode_body(request)
    if body is None:
        return bad_request("invalid request")

    current = _set_maintenance(body["maintenance"])
    return JsonResponse({"maintenance": current})


def require_service_mode_body(request):
    """Parse and validate the service-mode JSON body.

    Returns the parsed body dict on success, or ``None`` if the body is not
    exact JSON ``{"maintenance":true}`` / ``{"maintenance":false}``.
    """
    from ..http import parse_json

    body = parse_json(request)
    if not isinstance(body, dict):
        return None
    if set(body.keys()) != {"maintenance"}:
        return None
    if not isinstance(body["maintenance"], bool):
        return None
    return body
