"""Per-character inventory stack views for play campaigns."""

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from .common import require_actor, require_play_campaign_member_or_owner
from ..http import bad_request, conflict, forbidden, not_found, parse_json, require_method
from ..db import (
    _add_play_inventory_item,
    _get_play_inventory,
    _remove_play_inventory_item,
    db_conn,
)

VALID_ITEM_IDS = {
    "healing-potion",
    "torch",
    "leather-armor",
    "ring-of-protection",
    "amulet-of-health",
}

CONSUMABLE_EFFECTS = {
    "healing-potion": {"type": "healing", "hp_restored": 5},
}


@csrf_exempt
def play_inventory_items(request, id, character_id):
    if request.method == "POST":
        return add_play_inventory_item(request, id, character_id)
    if request.method == "GET":
        return get_play_inventory_items(request, id, character_id)
    return require_method(request, "GET", "POST")


def _require_character_owner(conn, actor, campaign_id, character_id):
    """Return the member row or a 404/403 error response for non-owners."""
    member = conn.execute(
        "SELECT character_id, owner FROM play_campaign_members "
        "WHERE campaign_id = ? AND character_id = ?",
        (campaign_id, character_id),
    ).fetchone()
    if member is None:
        return None, not_found("character not found")
    if actor["username"] != member["owner"]:
        return None, forbidden()
    return member, None


@csrf_exempt
def add_play_inventory_item(request, id, character_id):
    bad = require_method(request, "POST")
    if bad:
        return bad

    actor, err = require_actor(request)
    if err is not None:
        return err

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")
    try:
        item_id = body["item_id"]
        quantity = body["quantity"]
        if not isinstance(item_id, str) or not isinstance(quantity, int) or isinstance(quantity, bool):
            raise ValueError
        if quantity <= 0:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    if item_id not in VALID_ITEM_IDS:
        return bad_request("invalid request")

    with db_conn() as conn:
        campaign = conn.execute(
            "SELECT id FROM play_campaigns WHERE id = ?", (id,)
        ).fetchone()
        if campaign is None:
            return not_found("campaign not found")

        member, err = _require_character_owner(conn, actor, id, character_id)
        if err is not None:
            return err

        total = _add_play_inventory_item(conn, id, character_id, item_id, quantity)

    return JsonResponse(
        {
            "character_id": character_id,
            "item_id": item_id,
            "quantity": quantity,
            "total_quantity": total,
        },
        status=201,
    )


@csrf_exempt
def get_play_inventory_items(request, id, character_id):
    bad = require_method(request, "GET")
    if bad:
        return bad

    actor, campaign, err = require_play_campaign_member_or_owner(request, id)
    if err is not None:
        return err

    with db_conn() as conn:
        member = conn.execute(
            "SELECT character_id FROM play_campaign_members "
            "WHERE campaign_id = ? AND character_id = ?",
            (id, character_id),
        ).fetchone()
        if member is None:
            return not_found("character not found")

        items = _get_play_inventory(conn, id, character_id)

    return JsonResponse({"character_id": character_id, "items": items})


@csrf_exempt
def consume_item(request, id, character_id, item_id):
    bad = require_method(request, "POST")
    if bad:
        return bad

    actor, err = require_actor(request)
    if err is not None:
        return err

    if item_id not in VALID_ITEM_IDS:
        return bad_request("invalid request")
    if item_id not in CONSUMABLE_EFFECTS:
        return bad_request("invalid request")

    with db_conn() as conn:
        campaign = conn.execute(
            "SELECT id FROM play_campaigns WHERE id = ?", (id,)
        ).fetchone()
        if campaign is None:
            return not_found("campaign not found")

        member, err = _require_character_owner(conn, actor, id, character_id)
        if err is not None:
            return err

        try:
            total = _remove_play_inventory_item(conn, id, character_id, item_id, 1)
        except ValueError:
            return conflict("quantity exceeds held stack")

    return JsonResponse(
        {
            "character_id": character_id,
            "item_id": item_id,
            "quantity_consumed": 1,
            "total_quantity": total,
            "effect": CONSUMABLE_EFFECTS[item_id],
        }
    )


@csrf_exempt
def remove_play_inventory_item(request, id, character_id, item_id):
    bad = require_method(request, "DELETE")
    if bad:
        return bad

    actor, err = require_actor(request)
    if err is not None:
        return err

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")
    try:
        quantity = body["quantity"]
        if not isinstance(quantity, int) or isinstance(quantity, bool):
            raise ValueError
        if quantity <= 0:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    if item_id not in VALID_ITEM_IDS:
        return bad_request("invalid request")

    with db_conn() as conn:
        campaign = conn.execute(
            "SELECT id FROM play_campaigns WHERE id = ?", (id,)
        ).fetchone()
        if campaign is None:
            return not_found("campaign not found")

        member, err = _require_character_owner(conn, actor, id, character_id)
        if err is not None:
            return err

        try:
            total = _remove_play_inventory_item(conn, id, character_id, item_id, quantity)
        except ValueError:
            return conflict("quantity exceeds held stack")

    return JsonResponse(
        {
            "character_id": character_id,
            "item_id": item_id,
            "quantity": quantity,
            "total_quantity": total,
        }
    )
