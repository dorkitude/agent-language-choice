"""Stateless character math: ability modifiers, proficiency bonus, derived HP/AC."""

import json

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from dndsite.rules import ability_modifier, numeric, proficiency_bonus
from dndsite.views._util import json_body

ABILITY_KEYS = ("str", "dex", "con", "int", "wis", "cha")


@csrf_exempt
def ability_modifier_view(request):
    if request.method != "POST":
        return JsonResponse({"error": "method not allowed"}, status=405)
    try:
        body = json_body(request)
        score = body["score"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return JsonResponse({"error": "invalid request"}, status=400)

    modifier = ability_modifier(score)
    if modifier is None:
        return JsonResponse({"error": "invalid score"}, status=400)

    return JsonResponse({"score": score, "modifier": modifier})


@csrf_exempt
def proficiency_view(request):
    if request.method != "POST":
        return JsonResponse({"error": "method not allowed"}, status=405)
    try:
        body = json_body(request)
        level = body["level"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return JsonResponse({"error": "invalid request"}, status=400)

    bonus = proficiency_bonus(level)
    if bonus is None:
        return JsonResponse({"error": "invalid level"}, status=400)

    return JsonResponse({"level": level, "proficiency_bonus": bonus})


@csrf_exempt
def derived_stats(request):
    if request.method != "POST":
        return JsonResponse({"error": "method not allowed"}, status=405)
    try:
        body = json_body(request)
        level = body["level"]
        abilities = body["abilities"]
        armor = body["armor"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return JsonResponse({"error": "invalid request"}, status=400)

    prof_bonus = proficiency_bonus(level)
    if prof_bonus is None:
        return JsonResponse({"error": "invalid level"}, status=400)

    if not isinstance(abilities, dict) or not isinstance(armor, dict):
        return JsonResponse({"error": "invalid request"}, status=400)

    modifiers = {}
    for key in ABILITY_KEYS:
        if key not in abilities:
            return JsonResponse({"error": "invalid request"}, status=400)
        mod = ability_modifier(abilities[key])
        if mod is None:
            return JsonResponse({"error": "invalid ability score"}, status=400)
        modifiers[key] = mod

    try:
        base = armor["base"]
        shield = armor["shield"]
        dex_cap = armor["dex_cap"]
    except (KeyError, TypeError):
        return JsonResponse({"error": "invalid request"}, status=400)

    if not isinstance(base, (int, float)) or isinstance(base, bool):
        return JsonResponse({"error": "invalid request"}, status=400)
    if not isinstance(shield, bool):
        return JsonResponse({"error": "invalid request"}, status=400)
    if not isinstance(dex_cap, (int, float)) or isinstance(dex_cap, bool):
        return JsonResponse({"error": "invalid request"}, status=400)

    hp_max = level * (6 + modifiers["con"])
    shield_bonus = 2 if shield else 0
    armor_class = numeric(base + min(modifiers["dex"], dex_cap) + shield_bonus)

    return JsonResponse(
        {
            "level": level,
            "proficiency_bonus": prof_bonus,
            "hp_max": hp_max,
            "armor_class": armor_class,
            "modifiers": modifiers,
        }
    )
