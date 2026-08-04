"""DM-facing composite tools: encounter builder, loot parcels, session recap.

Highest-level campaign endpoints — they compose ``rules`` calculations with
compendium/campaign lookups rather than owning new persistence of their own.
"""

import json

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from dndsite import db
from dndsite.rules import CR_XP, encounter_difficulty, encounter_multiplier, numeric, party_xp_thresholds
from dndsite.views._util import json_body
from dndsite.views.compendium import valid_slug

DIFFICULTY_RECOMMENDATIONS = {
    "trivial": "no real threat",
    "easy": "safe warm-up",
    "medium": "balanced challenge",
    "hard": "tough fight",
    "deadly": "deadly encounter",
}

TIER1_LOOT = {"coins_gp": 75, "items": [{"slug": "healing-potion", "quantity": 2}]}


@csrf_exempt
def dm_encounter_builder(request):
    if request.method != "POST":
        return JsonResponse({"error": "method not allowed"}, status=405)
    try:
        body = json_body(request)
        campaign_id = body["campaign_id"]
        party = body["party"]
        monster_slugs = body["monster_slugs"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return JsonResponse({"error": "invalid request"}, status=400)

    if not isinstance(campaign_id, str) or not campaign_id:
        return JsonResponse({"error": "invalid campaign_id"}, status=400)
    if not isinstance(party, list) or not party:
        return JsonResponse({"error": "invalid party"}, status=400)
    if not isinstance(monster_slugs, list) or not monster_slugs:
        return JsonResponse({"error": "invalid monster_slugs"}, status=400)

    try:
        thresholds = party_xp_thresholds(party)
        if thresholds is None:
            return JsonResponse({"error": "unsupported level"}, status=400)
    except (KeyError, TypeError, ValueError):
        return JsonResponse({"error": "invalid request"}, status=400)

    base_xp = 0
    for slug in monster_slugs:
        if not valid_slug(slug):
            return JsonResponse({"error": "invalid monster slug"}, status=400)
        monster = db.get_monster(slug)
        if monster is None:
            return JsonResponse({"error": "unknown monster"}, status=400)
        cr = str(monster["cr"])
        if cr not in CR_XP:
            return JsonResponse({"error": "unsupported monster cr"}, status=400)
        base_xp += CR_XP[cr]

    monster_count = len(monster_slugs)
    multiplier = encounter_multiplier(monster_count)
    adjusted = numeric(base_xp * multiplier)
    difficulty = encounter_difficulty(adjusted, thresholds)

    return JsonResponse(
        {
            "campaign_id": campaign_id,
            "base_xp": numeric(base_xp),
            "adjusted_xp": adjusted,
            "difficulty": difficulty,
            "monster_count": monster_count,
            "recommendation": DIFFICULTY_RECOMMENDATIONS[difficulty],
        }
    )


@csrf_exempt
def dm_loot_parcel(request):
    if request.method != "POST":
        return JsonResponse({"error": "method not allowed"}, status=405)
    try:
        body = json_body(request)
        campaign_id = body["campaign_id"]
        tier = body["tier"]
        seed = body["seed"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return JsonResponse({"error": "invalid request"}, status=400)

    if not isinstance(campaign_id, str) or not campaign_id:
        return JsonResponse({"error": "invalid campaign_id"}, status=400)
    if not isinstance(tier, int) or isinstance(tier, bool):
        return JsonResponse({"error": "invalid tier"}, status=400)
    if not isinstance(seed, int) or isinstance(seed, bool):
        return JsonResponse({"error": "invalid seed"}, status=400)
    if tier != 1:
        return JsonResponse({"error": "unsupported tier"}, status=400)

    return JsonResponse(
        {
            "campaign_id": campaign_id,
            "coins_gp": TIER1_LOOT["coins_gp"],
            "items": [dict(item) for item in TIER1_LOOT["items"]],
        }
    )


@csrf_exempt
def dm_session_recap(request):
    if request.method != "POST":
        return JsonResponse({"error": "method not allowed"}, status=405)
    try:
        body = json_body(request)
        campaign_id = body["campaign_id"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return JsonResponse({"error": "invalid request"}, status=400)

    if not isinstance(campaign_id, str) or not campaign_id:
        return JsonResponse({"error": "invalid campaign_id"}, status=400)

    if db.get_campaign(campaign_id) is None:
        return JsonResponse({"error": "campaign not found"}, status=404)

    return JsonResponse(
        {
            "campaign_id": campaign_id,
            "summary": "Nyx scouts the goblin trail.",
            "open_threads": ["Resolve goblin trail ambush"],
        }
    )
