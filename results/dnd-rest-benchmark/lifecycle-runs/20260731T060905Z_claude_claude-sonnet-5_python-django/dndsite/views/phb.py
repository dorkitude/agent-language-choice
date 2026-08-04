"""PHB reference rules: spell slots, long-rest recovery, equipment load/encumbrance.

Pure computation against small seeded lookup tables — no persistence.
"""

import json

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from dndsite.rules import numeric
from dndsite.views._util import json_body

# Only wizard level 5 is seeded; unsupported class/level combos are rejected below.
SPELL_SLOTS_TABLE = {
    ("wizard", 5): {"1": 4, "2": 3, "3": 2},
}


@csrf_exempt
def phb_spell_slots(request):
    if request.method != "POST":
        return JsonResponse({"error": "method not allowed"}, status=405)
    try:
        body = json_body(request)
        class_name = body["class"]
        level = body["level"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return JsonResponse({"error": "invalid request"}, status=400)

    if not isinstance(class_name, str) or not isinstance(level, int) or isinstance(level, bool):
        return JsonResponse({"error": "invalid request"}, status=400)

    slots = SPELL_SLOTS_TABLE.get((class_name, level))
    if slots is None:
        return JsonResponse({"error": "unsupported class/level"}, status=400)

    return JsonResponse({"class": class_name, "level": level, "slots": slots})


@csrf_exempt
def phb_long_rest(request):
    if request.method != "POST":
        return JsonResponse({"error": "method not allowed"}, status=405)
    try:
        body = json_body(request)
        level = body["level"]
        hp_current = body["hp_current"]
        hp_max = body["hp_max"]
        hit_dice_spent = body["hit_dice_spent"]
        exhaustion_level = body["exhaustion_level"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return JsonResponse({"error": "invalid request"}, status=400)

    fields = (level, hp_current, hp_max, hit_dice_spent, exhaustion_level)
    if not all(isinstance(v, int) and not isinstance(v, bool) for v in fields):
        return JsonResponse({"error": "invalid request"}, status=400)
    if level < 1 or hp_max < 0 or hp_current < 0 or hit_dice_spent < 0 or exhaustion_level < 0:
        return JsonResponse({"error": "invalid request"}, status=400)

    max_recoverable = max(level // 2, 1)
    recovered = min(hit_dice_spent, max_recoverable)
    new_hit_dice_spent = hit_dice_spent - recovered
    new_exhaustion = max(exhaustion_level - 1, 0)

    return JsonResponse(
        {
            "hp_current": hp_max,
            "hit_dice_spent": new_hit_dice_spent,
            "exhaustion_level": new_exhaustion,
        }
    )


@csrf_exempt
def phb_equipment_load(request):
    if request.method != "POST":
        return JsonResponse({"error": "method not allowed"}, status=405)
    try:
        body = json_body(request)
        strength = body["strength"]
        weight = body["weight"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return JsonResponse({"error": "invalid request"}, status=400)

    if not isinstance(strength, (int, float)) or isinstance(strength, bool):
        return JsonResponse({"error": "invalid request"}, status=400)
    if not isinstance(weight, (int, float)) or isinstance(weight, bool):
        return JsonResponse({"error": "invalid request"}, status=400)
    if strength < 0 or weight < 0:
        return JsonResponse({"error": "invalid request"}, status=400)

    capacity = numeric(strength * 15)
    encumbered = weight > capacity

    return JsonResponse({"capacity": capacity, "weight": numeric(weight), "encumbered": encumbered})
