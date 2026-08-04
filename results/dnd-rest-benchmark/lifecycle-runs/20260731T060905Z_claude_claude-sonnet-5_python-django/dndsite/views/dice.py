"""Dice expression stats and ability checks. Stateless — no persistence."""

import json
import re

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from dndsite.rules import numeric
from dndsite.views._util import json_body

DICE_RE = re.compile(r"^(\d+)d(\d+)(?:([+-])(\d+))?$")


@csrf_exempt
def dice_stats(request):
    if request.method != "POST":
        return JsonResponse({"error": "method not allowed"}, status=405)
    try:
        body = json_body(request)
        expression = body["expression"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return JsonResponse({"error": "invalid request"}, status=400)

    match = DICE_RE.match(expression.strip()) if isinstance(expression, str) else None
    if not match:
        return JsonResponse({"error": "invalid expression"}, status=400)

    count = int(match.group(1))
    sides = int(match.group(2))
    sign = match.group(3)
    mod_value = match.group(4)
    modifier = int(mod_value) if mod_value else 0
    if sign == "-":
        modifier = -modifier

    if count <= 0 or sides <= 0:
        return JsonResponse({"error": "invalid expression"}, status=400)

    min_val = count * 1 + modifier
    max_val = count * sides + modifier
    average = numeric((count * (sides + 1) / 2) + modifier)

    return JsonResponse(
        {
            "dice_count": count,
            "sides": sides,
            "modifier": modifier,
            "min": min_val,
            "max": max_val,
            "average": average,
        }
    )


@csrf_exempt
def ability_check(request):
    if request.method != "POST":
        return JsonResponse({"error": "method not allowed"}, status=405)
    try:
        body = json_body(request)
        roll = body["roll"]
        modifier = body["modifier"]
        dc = body["dc"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return JsonResponse({"error": "invalid request"}, status=400)

    if not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in (roll, modifier, dc)):
        return JsonResponse({"error": "invalid request"}, status=400)

    total = roll + modifier
    success = total >= dc
    margin = total - dc

    return JsonResponse({"total": numeric(total), "success": success, "margin": numeric(margin)})
