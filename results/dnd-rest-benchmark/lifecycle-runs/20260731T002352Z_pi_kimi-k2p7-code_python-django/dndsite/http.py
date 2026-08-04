"""HTTP request/response utilities shared by the API views."""

import json

from django.http import HttpResponseBadRequest, JsonResponse


def parse_json(request):
    """Parse the request body as JSON, returning ``None`` on failure."""
    try:
        return json.loads(request.body)
    except (json.JSONDecodeError, TypeError):
        return None


def require_method(request, *methods):
    """Return a 400 response if the request method is not allowed.

    The API returns ``HttpResponseBadRequest`` with an empty body for
    disallowed methods, matching the original behavior. A return value of
    ``None`` means the method is acceptable.
    """
    if request.method not in methods:
        return HttpResponseBadRequest()
    return None


def bad_request(message="invalid request"):
    return JsonResponse({"error": message}, status=400)


def unauthorized(message="invalid credentials"):
    return JsonResponse({"error": message}, status=401)


def conflict(message):
    return JsonResponse({"error": message}, status=409)


def not_found(message):
    return JsonResponse({"error": message}, status=404)


def forbidden(message="forbidden"):
    return JsonResponse({"error": message}, status=403)
