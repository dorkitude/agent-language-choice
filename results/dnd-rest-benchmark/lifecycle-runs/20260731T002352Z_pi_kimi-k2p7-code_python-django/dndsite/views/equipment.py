"""Equipment and attunement views for play campaigns."""

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from .common import require_actor, require_play_campaign_member_or_owner
from ..db import (
    _count_play_attunements,
    _get_play_equipment,
    _set_play_attunement,
    _set_play_equipment,
    db_conn,
)
from ..http import bad_request, conflict, forbidden, not_found, parse_json, require_method

VALID_SLOTS = {"armor", "accessory"}

ITEM_SLOTS = {
    "leather-armor": "armor",
    "ring-of-protection": "accessory",
    "amulet-of-health": "accessory",
}

ATTUNABLE_ITEMS = {"ring-of-protection", "amulet-of-health"}


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


def _equipment_response(character_id, slot, item_id, attuned):
    return {
        "character_id": character_id,
        "slot": slot,
        "item_id": item_id,
        "attuned": attuned,
    }


@csrf_exempt
def play_equipment(request, id, character_id, slot):
    if request.method == "GET":
        return _get_equipment(request, id, character_id, slot)
    if request.method == "PUT":
        return _equip_item(request, id, character_id, slot)
    return require_method(request, "GET", "PUT")


@csrf_exempt
def _equip_item(request, id, character_id, slot):
    bad = require_method(request, "PUT")
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
        if not isinstance(item_id, str):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    if slot not in VALID_SLOTS:
        return bad_request("invalid request")
    if item_id not in ITEM_SLOTS:
        return bad_request("invalid request")
    if ITEM_SLOTS[item_id] != slot:
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

        inventory = conn.execute(
            "SELECT quantity FROM play_character_inventory "
            "WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
            (id, character_id, item_id),
        ).fetchone()
        if inventory is None or inventory["quantity"] < 1:
            return bad_request("invalid request")

        _set_play_equipment(conn, id, character_id, slot, item_id, attuned=False)

    return JsonResponse(_equipment_response(character_id, slot, item_id, False))


@csrf_exempt
def _get_equipment(request, id, character_id, slot):
    bad = require_method(request, "GET")
    if bad:
        return bad

    actor, campaign, err = require_play_campaign_member_or_owner(request, id)
    if err is not None:
        return err

    if slot not in VALID_SLOTS:
        return bad_request("invalid request")

    with db_conn() as conn:
        member = conn.execute(
            "SELECT character_id FROM play_campaign_members "
            "WHERE campaign_id = ? AND character_id = ?",
            (id, character_id),
        ).fetchone()
        if member is None:
            return not_found("character not found")

        row = _get_play_equipment(conn, id, character_id, slot)

    if row is None:
        return JsonResponse(_equipment_response(character_id, slot, "", False))
    return JsonResponse(
        _equipment_response(character_id, slot, row["item_id"], bool(row["attuned"]))
    )


@csrf_exempt
def attune_item(request, id, character_id, slot):
    bad = require_method(request, "POST")
    if bad:
        return bad

    actor, err = require_actor(request)
    if err is not None:
        return err

    with db_conn() as conn:
        campaign = conn.execute(
            "SELECT id FROM play_campaigns WHERE id = ?", (id,)
        ).fetchone()
        if campaign is None:
            return not_found("campaign not found")

        member, err = _require_character_owner(conn, actor, id, character_id)
        if err is not None:
            return err

        row = _get_play_equipment(conn, id, character_id, slot)
        if row is None or not row["item_id"]:
            return bad_request("invalid request")

        item_id = row["item_id"]
        if item_id not in ATTUNABLE_ITEMS or slot != "accessory":
            return bad_request("invalid request")

        attunement_count = _count_play_attunements(conn, id, character_id)
        if attunement_count >= 1:
            return conflict("already attuned")

        _set_play_attunement(conn, id, character_id, slot, True)
        attunement_count = _count_play_attunements(conn, id, character_id)

    return JsonResponse(
        {
            "character_id": character_id,
            "slot": slot,
            "item_id": item_id,
            "attuned": True,
            "attunement_count": attunement_count,
            "max_attunements": 1,
        }
    )
