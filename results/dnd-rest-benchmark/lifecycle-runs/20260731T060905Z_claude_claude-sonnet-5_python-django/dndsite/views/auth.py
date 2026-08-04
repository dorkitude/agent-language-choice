"""User registration and login. No server-side session store — see ``_util.authenticate``."""

import json
import re

from django.contrib.auth.hashers import check_password, make_password
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from dndsite import db
from dndsite.views._util import json_body

USERNAME_RE = re.compile(r"^[a-z0-9_-]{2,32}$")
VALID_ROLES = ("dm", "player")


def _hash_password(password):
    return make_password(password)


def _verify_password(password, hashed):
    return check_password(password, hashed)


@csrf_exempt
def auth_register(request):
    if request.method != "POST":
        return JsonResponse({"error": "method not allowed"}, status=405)
    try:
        body = json_body(request)
        username = body["username"]
        password = body["password"]
        role = body["role"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return JsonResponse({"error": "invalid request"}, status=400)

    if not isinstance(username, str) or not USERNAME_RE.match(username):
        return JsonResponse({"error": "invalid username"}, status=400)
    if not isinstance(password, str) or len(password) < 8:
        return JsonResponse({"error": "invalid password"}, status=400)
    if role not in VALID_ROLES:
        return JsonResponse({"error": "invalid role"}, status=400)

    if db.get_user(username) is not None:
        return JsonResponse({"error": "username already exists"}, status=409)

    db.create_user(username, role, _hash_password(password))

    return JsonResponse({"username": username, "role": role}, status=201)


@csrf_exempt
def auth_login(request):
    if request.method != "POST":
        return JsonResponse({"error": "method not allowed"}, status=405)
    try:
        body = json_body(request)
        username = body["username"]
        password = body["password"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return JsonResponse({"error": "invalid request"}, status=400)

    if not isinstance(username, str) or not isinstance(password, str):
        return JsonResponse({"error": "invalid request"}, status=400)

    user = db.get_user(username)
    if user is None or not _verify_password(password, user["password_hash"]):
        return JsonResponse({"error": "invalid credentials"}, status=401)

    return JsonResponse({"username": username, "token": f"session-{username}"})
