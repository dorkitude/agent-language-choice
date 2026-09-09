"""Shop views for play campaign settlements."""

import json
import sqlite3

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from .common import (
    require_actor,
    require_play_campaign_member_or_owner,
)
from .inventory import VALID_ITEM_IDS

from ..http import bad_request, conflict, forbidden, not_found, parse_json, require_method
from ..db import (
    _add_play_inventory_item,
    _get_play_shop,
    _remove_play_inventory_item,
    _set_character_gold,
    db_conn,
)


def _shop_response(shop_id, name, stock, buy_price, sell_price):
    """Build the exact shop response dict."""
    return {
        "shop_id": shop_id,
        "name": name,
        "stock": stock,
        "buy_price": buy_price,
        "sell_price": sell_price,
    }


def _validate_stock(stock):
    """Validate and return a stock dict.

    Raises ``ValueError`` for invalid input.
    """
    if not isinstance(stock, dict) or not stock:
        raise ValueError
    validated = {}
    for item_id, quantity in stock.items():
        if not isinstance(item_id, str) or item_id not in VALID_ITEM_IDS:
            raise ValueError
        if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity <= 0:
            raise ValueError
        validated[item_id] = quantity
    return validated


@csrf_exempt
def create_shop(request, id, settlement_id):
    """POST /v1/play/campaigns/{id}/settlements/{settlement_id}/shops"""
    bad = require_method(request, "POST")
    if bad:
        return bad

    actor, err = require_actor(request, "dm")
    if err is not None:
        return err

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")

    try:
        shop_id = body["shop_id"]
        name = body["name"]
        stock = body["stock"]
        buy_price = body["buy_price"]
        sell_price = body["sell_price"]
        if not isinstance(shop_id, str) or not shop_id:
            raise ValueError
        if not isinstance(name, str) or not name:
            raise ValueError
        validated_stock = _validate_stock(stock)
        if not isinstance(buy_price, int) or isinstance(buy_price, bool) or buy_price <= 0:
            raise ValueError
        if not isinstance(sell_price, int) or isinstance(sell_price, bool) or sell_price < 0:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    with db_conn() as conn:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (id,)
        ).fetchone()
        if campaign is None:
            return not_found("campaign not found")
        if actor["username"] != campaign["owner"]:
            return forbidden()

        settlement = conn.execute(
            "SELECT 1 FROM play_settlements WHERE campaign_id = ? AND settlement_id = ?",
            (id, settlement_id),
        ).fetchone()
        if settlement is None:
            return not_found("settlement not found")

        try:
            conn.execute(
                "INSERT INTO play_shops (campaign_id, settlement_id, shop_id, name, stock_json, buy_price, sell_price) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (id, settlement_id, shop_id, name, json.dumps(validated_stock), buy_price, sell_price),
            )
        except sqlite3.IntegrityError:
            return conflict("shop already exists")

    return JsonResponse(
        _shop_response(shop_id, name, validated_stock, buy_price, sell_price),
        status=201,
    )


@csrf_exempt
def get_shop(request, id, settlement_id, shop_id):
    """GET /v1/play/campaigns/{id}/settlements/{settlement_id}/shops/{shop_id}"""
    bad = require_method(request, "GET")
    if bad:
        return bad

    actor, campaign, err = require_play_campaign_member_or_owner(request, id)
    if err is not None:
        return err

    with db_conn() as conn:
        settlement = conn.execute(
            "SELECT 1 FROM play_settlements WHERE campaign_id = ? AND settlement_id = ?",
            (id, settlement_id),
        ).fetchone()
        if settlement is None:
            return not_found("settlement not found")

        shop = _get_play_shop(conn, id, settlement_id, shop_id)
        if shop is None:
            return not_found("shop not found")

        is_owner = actor["username"] == campaign["owner"]
        if not is_owner:
            member = conn.execute(
                "SELECT character_id FROM play_campaign_members "
                "WHERE campaign_id = ? AND username = ?",
                (id, actor["username"]),
            ).fetchone()
            character_id = member["character_id"]
            discovered = conn.execute(
                "SELECT 1 FROM play_settlement_discoveries "
                "WHERE campaign_id = ? AND settlement_id = ? AND character_id = ?",
                (id, settlement_id, character_id),
            ).fetchone() is not None
            if not discovered:
                return not_found("shop not found")

    return JsonResponse(
        _shop_response(
            shop_id,
            shop["name"],
            json.loads(shop["stock_json"]),
            shop["buy_price"],
            shop["sell_price"],
        )
    )


def _require_character_owner(conn, actor, campaign_id, settlement_id, character_id):
    """Return the member row or a 404/403 error for non-owners / the DM."""
    settlement = conn.execute(
        "SELECT 1 FROM play_settlements WHERE campaign_id = ? AND settlement_id = ?",
        (campaign_id, settlement_id),
    ).fetchone()
    if settlement is None:
        return None, not_found("settlement not found")

    member = conn.execute(
        "SELECT character_id, owner, gold FROM play_campaign_members "
        "WHERE campaign_id = ? AND character_id = ?",
        (campaign_id, character_id),
    ).fetchone()
    if member is None:
        return None, not_found("character not found")

    if actor["role"] == "dm":
        return None, forbidden()

    if actor["username"] != member["owner"]:
        return None, forbidden()

    return member, None


@csrf_exempt
def buy_item(request, id, settlement_id, shop_id):
    """POST /v1/play/campaigns/{id}/settlements/{settlement_id}/shops/{shop_id}/buy"""
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
        character_id = body["character_id"]
        item_id = body["item_id"]
        quantity = body["quantity"]
        if not isinstance(character_id, str) or not isinstance(item_id, str):
            raise ValueError
        if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity <= 0:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    if item_id not in VALID_ITEM_IDS:
        return bad_request("invalid request")

    with db_conn() as conn:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (id,)
        ).fetchone()
        if campaign is None:
            return not_found("campaign not found")

        shop = _get_play_shop(conn, id, settlement_id, shop_id)
        if shop is None:
            return not_found("shop not found")

        member, err = _require_character_owner(conn, actor, id, settlement_id, character_id)
        if err is not None:
            return err

        stock = json.loads(shop["stock_json"])
        if item_id not in stock or stock[item_id] < quantity:
            return conflict("insufficient stock")

        cost = shop["buy_price"] * quantity
        if member["gold"] < cost:
            return conflict("insufficient gold")

        new_stock = stock[item_id] - quantity
        if new_stock == 0:
            del stock[item_id]
        else:
            stock[item_id] = new_stock

        new_gold = member["gold"] - cost

        _set_character_gold(conn, id, character_id, new_gold)
        _add_play_inventory_item(conn, id, character_id, item_id, quantity)
        conn.execute(
            "UPDATE play_shops SET stock_json = ? "
            "WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ?",
            (json.dumps(stock), id, settlement_id, shop_id),
        )

    return JsonResponse(
        {
            "character_id": character_id,
            "item_id": item_id,
            "quantity": quantity,
            "gold": new_gold,
            "stock": new_stock,
        }
    )


@csrf_exempt
def sell_item(request, id, settlement_id, shop_id):
    """POST /v1/play/campaigns/{id}/settlements/{settlement_id}/shops/{shop_id}/sell"""
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
        character_id = body["character_id"]
        item_id = body["item_id"]
        quantity = body["quantity"]
        if not isinstance(character_id, str) or not isinstance(item_id, str):
            raise ValueError
        if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity <= 0:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    if item_id not in VALID_ITEM_IDS:
        return bad_request("invalid request")

    with db_conn() as conn:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (id,)
        ).fetchone()
        if campaign is None:
            return not_found("campaign not found")

        shop = _get_play_shop(conn, id, settlement_id, shop_id)
        if shop is None:
            return not_found("shop not found")

        member, err = _require_character_owner(conn, actor, id, settlement_id, character_id)
        if err is not None:
            return err

        inv_row = conn.execute(
            "SELECT quantity FROM play_character_inventory "
            "WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
            (id, character_id, item_id),
        ).fetchone()
        if inv_row is None or inv_row["quantity"] < quantity:
            return conflict("insufficient quantity")

        stock = json.loads(shop["stock_json"])
        stock[item_id] = stock.get(item_id, 0) + quantity
        new_stock = stock[item_id]

        new_gold = member["gold"] + shop["sell_price"] * quantity

        _set_character_gold(conn, id, character_id, new_gold)
        _remove_play_inventory_item(conn, id, character_id, item_id, quantity)
        conn.execute(
            "UPDATE play_shops SET stock_json = ? "
            "WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ?",
            (json.dumps(stock), id, settlement_id, shop_id),
        )

    return JsonResponse(
        {
            "character_id": character_id,
            "item_id": item_id,
            "quantity": quantity,
            "gold": new_gold,
            "stock": new_stock,
        }
    )
