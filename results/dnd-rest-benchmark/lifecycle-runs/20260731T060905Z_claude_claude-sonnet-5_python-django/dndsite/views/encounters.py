"""Adjusted-XP difficulty calculation and initiative ordering. Stateless — no persistence."""

import json

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from dndsite.rules import CR_XP, encounter_difficulty, encounter_multiplier, numeric, party_xp_thresholds
from dndsite.views._util import json_body


@csrf_exempt
def adjusted_xp(request):
    if request.method != "POST":
        return JsonResponse({"error": "method not allowed"}, status=405)
    try:
        body = json_body(request)
        party = body["party"]
        monsters = body["monsters"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return JsonResponse({"error": "invalid request"}, status=400)

    try:
        base_xp = 0
        monster_count = 0
        for monster in monsters:
            cr = str(monster["cr"])
            count = int(monster["count"])
            if cr not in CR_XP or count < 0:
                return JsonResponse({"error": "invalid monster"}, status=400)
            base_xp += CR_XP[cr] * count
            monster_count += count

        thresholds = party_xp_thresholds(party)
        if thresholds is None:
            return JsonResponse({"error": "unsupported level"}, status=400)
    except (KeyError, TypeError, ValueError):
        return JsonResponse({"error": "invalid request"}, status=400)

    multiplier = encounter_multiplier(monster_count)
    adjusted = numeric(base_xp * multiplier)
    difficulty = encounter_difficulty(adjusted, thresholds)

    return JsonResponse(
        {
            "base_xp": base_xp,
            "monster_count": monster_count,
            "multiplier": multiplier,
            "adjusted_xp": adjusted,
            "difficulty": difficulty,
            "thresholds": thresholds,
        }
    )


@csrf_exempt
def initiative_order(request):
    if request.method != "POST":
        return JsonResponse({"error": "method not allowed"}, status=405)
    try:
        body = json_body(request)
        combatants = body["combatants"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return JsonResponse({"error": "invalid request"}, status=400)

    try:
        scored = []
        for combatant in combatants:
            name = combatant["name"]
            dex = combatant["dex"]
            roll = combatant["roll"]
            score = roll + dex
            scored.append({"name": name, "dex": dex, "score": score})
    except (KeyError, TypeError):
        return JsonResponse({"error": "invalid request"}, status=400)

    scored.sort(key=lambda c: (-c["score"], -c["dex"], c["name"]))

    order = [{"name": c["name"], "score": numeric(c["score"])} for c in scored]

    return JsonResponse({"order": order})
