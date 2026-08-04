"""Monster and item reference data: create + fetch by slug."""

import json
import re

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from dndsite import db
from dndsite.rules import numeric
from dndsite.views._util import json_body

SLUG_RE = re.compile(r"^[a-z0-9-]+$")


def valid_slug(slug):
    return isinstance(slug, str) and bool(SLUG_RE.match(slug))


@csrf_exempt
def monsters_collection(request):
    if request.method != "POST":
        return JsonResponse({"error": "method not allowed"}, status=405)
    try:
        body = json_body(request)
        slug = body["slug"]
        name = body["name"]
        cr = body["cr"]
        armor_class = body["armor_class"]
        hit_points = body["hit_points"]
        tags = body.get("tags", [])
    except (json.JSONDecodeError, KeyError, TypeError):
        return JsonResponse({"error": "invalid request"}, status=400)

    if not valid_slug(slug):
        return JsonResponse({"error": "invalid slug"}, status=400)
    if not isinstance(name, str) or not name:
        return JsonResponse({"error": "invalid name"}, status=400)
    if not isinstance(cr, str) or not cr:
        return JsonResponse({"error": "invalid cr"}, status=400)
    if not isinstance(armor_class, int) or isinstance(armor_class, bool):
        return JsonResponse({"error": "invalid armor_class"}, status=400)
    if not isinstance(hit_points, int) or isinstance(hit_points, bool):
        return JsonResponse({"error": "invalid hit_points"}, status=400)
    if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
        return JsonResponse({"error": "invalid tags"}, status=400)

    if db.get_monster(slug) is not None:
        return JsonResponse({"error": "monster already exists"}, status=409)

    monster = {
        "slug": slug,
        "name": name,
        "cr": cr,
        "armor_class": armor_class,
        "hit_points": hit_points,
        "tags": tags,
    }
    db.create_monster(monster)

    return JsonResponse(
        {
            "slug": slug,
            "name": name,
            "cr": cr,
            "armor_class": armor_class,
            "hit_points": hit_points,
        },
        status=201,
    )


def monster_detail(request, slug):
    if request.method != "GET":
        return JsonResponse({"error": "method not allowed"}, status=405)

    monster = db.get_monster(slug)
    if monster is None:
        return JsonResponse({"error": "monster not found"}, status=404)

    return JsonResponse(monster)


@csrf_exempt
def items_collection(request):
    if request.method != "POST":
        return JsonResponse({"error": "method not allowed"}, status=405)
    try:
        body = json_body(request)
        slug = body["slug"]
        name = body["name"]
        item_type = body["type"]
        rarity = body["rarity"]
        cost_gp = body["cost_gp"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return JsonResponse({"error": "invalid request"}, status=400)

    if not valid_slug(slug):
        return JsonResponse({"error": "invalid slug"}, status=400)
    if not isinstance(name, str) or not name:
        return JsonResponse({"error": "invalid name"}, status=400)
    if not isinstance(item_type, str) or not item_type:
        return JsonResponse({"error": "invalid type"}, status=400)
    if not isinstance(rarity, str) or not rarity:
        return JsonResponse({"error": "invalid rarity"}, status=400)
    if not isinstance(cost_gp, (int, float)) or isinstance(cost_gp, bool):
        return JsonResponse({"error": "invalid cost_gp"}, status=400)

    if db.get_item(slug) is not None:
        return JsonResponse({"error": "item already exists"}, status=409)

    item = {
        "slug": slug,
        "name": name,
        "type": item_type,
        "rarity": rarity,
        "cost_gp": numeric(cost_gp),
    }
    db.create_item(item)

    return JsonResponse(item, status=201)


def item_detail(request, slug):
    if request.method != "GET":
        return JsonResponse({"error": "method not allowed"}, status=405)

    item = db.get_item(slug)
    if item is None:
        return JsonResponse({"error": "item not found"}, status=404)

    return JsonResponse(item)
