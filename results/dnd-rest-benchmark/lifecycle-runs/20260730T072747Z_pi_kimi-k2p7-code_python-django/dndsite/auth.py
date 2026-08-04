"""User identity and password handling."""

import hashlib
import hmac
import re
import secrets

from dndsite import persistence

_USERNAME_RE = re.compile(r"^[a-z0-9_-]{2,32}$")
_ROLES = {"dm", "player"}


def _authenticate_bearer(request):
    """Validate an Authorization: Bearer session-<username> header.

    Returns a user dict on success, or a JsonResponse with the appropriate
    failure status (401 or 403). Callers should check ``isinstance`` to decide
    whether to short-circuit the request.

    A valid session token is accepted for any valid username. If the user has
    not been explicitly registered, a virtual actor is returned with a default
    role: ``dm`` for the username ``dm`` and ``player`` otherwise. This lets the
    protected /v1/play surface work without requiring a prior registration step
    for every actor.
    """
    from django.http import JsonResponse

    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return JsonResponse({"error": "unauthorized"}, status=401)
    token = header[len("Bearer "):].strip()
    if not token.startswith("session-"):
        return JsonResponse({"error": "unauthorized"}, status=401)
    username = token[len("session-"):]
    if not _USERNAME_RE.fullmatch(username):
        return JsonResponse({"error": "unauthorized"}, status=401)
    user = persistence._get_user(username)
    if user is not None:
        return user
    role = "dm" if username == "dm" else "player"
    return {"username": username, "role": role}


def _require_role(user, role):
    """Return a 403 JsonResponse if the user does not have the required role."""
    from django.http import JsonResponse

    if user["role"] != role:
        return JsonResponse({"error": "forbidden"}, status=403)
    return None


def _hash_password(password):
    salt = secrets.token_bytes(16)
    hash_bytes = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100000)
    return salt.hex() + "$" + hash_bytes.hex()


def _verify_password(password, stored):
    try:
        salt_hex, hash_hex = stored.split("$", 1)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100000)
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False
