"""Currency and trade views for live-play campaigns."""

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from .common import require_play_campaign_member_or_owner

from ..http import bad_request, conflict, forbidden, not_found, parse_json, require_method

from ..db import (
    _get_character_gold,
    _next_transactional_transfer_sequence,
    _next_transfer_id,
    _record_transactional_transfer,
    _record_transfer,
    _set_character_gold,
    db_conn,
)


class SimulatedFailure(Exception):
    """Raised to abort a transactional transfer without persisting changes."""


@csrf_exempt
def get_currency(request, id, character_id):
    bad = require_method(request, "GET")
    if bad:
        return bad

    actor, campaign, err = require_play_campaign_member_or_owner(request, id)
    if err is not None:
        return err

    with db_conn() as conn:
        gold = _get_character_gold(conn, id, character_id)
        if gold is None:
            return not_found("character not found")

    return JsonResponse({"character_id": character_id, "gold": gold})


@csrf_exempt
def transfer_currency(request, id, character_id):
    bad = require_method(request, "POST")
    if bad:
        return bad

    actor, campaign, err = require_play_campaign_member_or_owner(request, id)
    if err is not None:
        return err

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")
    try:
        to_character_id = body["to_character_id"]
        gold = body["gold"]
        if not isinstance(to_character_id, str) or not isinstance(gold, int) or isinstance(gold, bool):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    if gold <= 0:
        return bad_request("invalid request")

    if character_id == to_character_id:
        return bad_request("invalid request")

    with db_conn() as conn:
        source = conn.execute(
            "SELECT character_id, owner, gold FROM play_campaign_members "
            "WHERE campaign_id = ? AND character_id = ?",
            (id, character_id),
        ).fetchone()
        if source is None:
            return not_found("character not found")

        if actor["username"] != source["owner"]:
            return forbidden()

        destination = conn.execute(
            "SELECT character_id, gold FROM play_campaign_members "
            "WHERE campaign_id = ? AND character_id = ?",
            (id, to_character_id),
        ).fetchone()
        if destination is None:
            return bad_request("invalid request")

        if source["gold"] < gold:
            return conflict("insufficient gold")

        from_gold = source["gold"] - gold
        to_gold = destination["gold"] + gold

        _set_character_gold(conn, id, character_id, from_gold)
        _set_character_gold(conn, id, to_character_id, to_gold)

        transfer_id = _next_transfer_id(conn, id)
        _record_transfer(
            conn,
            id,
            transfer_id,
            character_id,
            to_character_id,
            gold,
            from_gold,
            to_gold,
        )

    return JsonResponse(
        {
            "from_character_id": character_id,
            "to_character_id": to_character_id,
            "gold": gold,
            "from_gold": from_gold,
            "to_gold": to_gold,
            "transfer_id": transfer_id,
        },
        status=201,
    )


@csrf_exempt
def transactional_transfers(request, id):
    """Dispatch GET/POST for /v1/play/campaigns/{id}/transactional-transfers."""
    bad = require_method(request, "GET", "POST")
    if bad:
        return bad
    if request.method == "POST":
        return create_transactional_transfer(request, id)
    return get_transactional_transfers(request, id)


@csrf_exempt
def create_transactional_transfer(request, id):
    bad = require_method(request, "POST")
    if bad:
        return bad

    actor, campaign, err = require_play_campaign_member_or_owner(request, id)
    if err is not None:
        return err

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")
    try:
        from_character_id = body["from_character_id"]
        to_character_id = body["to_character_id"]
        amount = body["amount"]
        simulate_failure = body["simulate_failure"]
        if not isinstance(from_character_id, str) or not isinstance(to_character_id, str):
            raise ValueError
        if not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
            raise ValueError
        if not isinstance(simulate_failure, bool):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    if from_character_id == to_character_id:
        return bad_request("invalid request")

    try:
        with db_conn() as conn:
            source = conn.execute(
                "SELECT character_id, owner, gold FROM play_campaign_members "
                "WHERE campaign_id = ? AND character_id = ?",
                (id, from_character_id),
            ).fetchone()
            if source is None:
                return bad_request("invalid request")

            if actor["username"] != source["owner"]:
                return forbidden()

            destination = conn.execute(
                "SELECT character_id, gold FROM play_campaign_members "
                "WHERE campaign_id = ? AND character_id = ?",
                (id, to_character_id),
            ).fetchone()
            if destination is None:
                return bad_request("invalid request")

            if source["gold"] < amount:
                return conflict("insufficient gold")

            if simulate_failure:
                raise SimulatedFailure()

            from_gold = source["gold"] - amount
            to_gold = destination["gold"] + amount

            _set_character_gold(conn, id, from_character_id, from_gold)
            _set_character_gold(conn, id, to_character_id, to_gold)

            sequence = _next_transactional_transfer_sequence(conn, id)
            _record_transactional_transfer(
                conn,
                id,
                sequence,
                from_character_id,
                to_character_id,
                amount,
                from_gold,
                to_gold,
            )
    except SimulatedFailure:
        return JsonResponse({"error": "simulated failure"}, status=500)

    return JsonResponse(
        {
            "from_character_id": from_character_id,
            "to_character_id": to_character_id,
            "amount": amount,
            "from_gold": from_gold,
            "to_gold": to_gold,
            "sequence": sequence,
        },
        status=201,
    )


@csrf_exempt
def get_transactional_transfers(request, id):
    bad = require_method(request, "GET")
    if bad:
        return bad

    actor, campaign, err = require_play_campaign_member_or_owner(request, id)
    if err is not None:
        return err

    with db_conn() as conn:
        rows = conn.execute(
            "SELECT from_character_id, to_character_id, amount, from_gold, to_gold, sequence "
            "FROM play_transactional_transfers WHERE campaign_id = ? ORDER BY sequence ASC",
            (id,),
        ).fetchall()

    transfers = [
        {
            "from_character_id": row["from_character_id"],
            "to_character_id": row["to_character_id"],
            "amount": row["amount"],
            "from_gold": row["from_gold"],
            "to_gold": row["to_gold"],
            "sequence": row["sequence"],
        }
        for row in rows
    ]

    return JsonResponse({"transfers": transfers})
