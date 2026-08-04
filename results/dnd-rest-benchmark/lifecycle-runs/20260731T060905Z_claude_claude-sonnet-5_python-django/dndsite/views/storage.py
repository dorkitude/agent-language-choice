"""Schema status/reset introspection endpoints."""

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from dndsite import db


def storage_status(request):
    if request.method != "GET":
        return JsonResponse({"error": "method not allowed"}, status=405)
    return JsonResponse(
        {
            "driver": "sqlite",
            "schema_version": db.SCHEMA_VERSION,
            "initialized": db.is_initialized(),
        }
    )


@csrf_exempt
def storage_reset(request):
    if request.method != "POST":
        return JsonResponse({"error": "method not allowed"}, status=405)
    db.reset_schema()
    return JsonResponse({"ok": True, "schema_version": db.SCHEMA_VERSION})
