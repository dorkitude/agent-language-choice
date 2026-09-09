"""Recipe catalog views for play campaigns."""

import json
import sqlite3

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from .common import (
    require_actor,
    require_play_campaign_dm_owner,
    require_play_campaign_member_or_owner,
)
from .inventory import VALID_ITEM_IDS

from ..http import bad_request, conflict, forbidden, not_found, parse_json, require_method
from ..db import (
    _add_play_inventory_item,
    _remove_play_inventory_item,
    db_conn,
)


def _validate_recipe_body(body):
    """Validate a recipe create request.

    Returns a tuple of (recipe_id, name, ingredients, output_item, output_quantity)
    or ``None`` if validation fails.
    """
    try:
        recipe_id = body["recipe_id"]
        name = body["name"]
        ingredients = body["ingredients"]
        output_item = body["output_item"]
        output_quantity = body["output_quantity"]
        if not isinstance(recipe_id, str) or not recipe_id:
            raise ValueError
        if not isinstance(name, str) or not name:
            raise ValueError
        if not isinstance(ingredients, dict) or not ingredients:
            raise ValueError
        for item_id, quantity in ingredients.items():
            if not isinstance(item_id, str) or item_id not in VALID_ITEM_IDS:
                raise ValueError
            if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity <= 0:
                raise ValueError
        if not isinstance(output_item, str) or output_item not in VALID_ITEM_IDS:
            raise ValueError
        if not isinstance(output_quantity, int) or isinstance(output_quantity, bool) or output_quantity <= 0:
            raise ValueError
        return recipe_id, name, ingredients, output_item, output_quantity
    except (KeyError, TypeError, ValueError):
        return None


def _recipe_response(recipe_id, name, ingredients, output_item, output_quantity):
    """Build the exact recipe response body."""
    return {
        "recipe_id": recipe_id,
        "name": name,
        "ingredients": ingredients,
        "output_item": output_item,
        "output_quantity": output_quantity,
    }


@csrf_exempt
def recipes(request, id):
    """GET/POST /v1/play/campaigns/{id}/recipes"""
    if request.method == "POST":
        return create_recipe(request, id)
    if request.method == "GET":
        return list_recipes(request, id)
    return require_method(request, "GET", "POST")


@csrf_exempt
def create_recipe(request, id):
    """POST /v1/play/campaigns/{id}/recipes"""
    bad = require_method(request, "POST")
    if bad:
        return bad

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")

    validated = _validate_recipe_body(body)
    if validated is None:
        return bad_request("invalid request")

    recipe_id, name, ingredients, output_item, output_quantity = validated

    actor, campaign, err = require_play_campaign_dm_owner(request, id)
    if err is not None:
        return err

    with db_conn() as conn:
        try:
            conn.execute(
                "INSERT INTO play_recipes (campaign_id, recipe_id, name, ingredients_json, output_item, output_quantity) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (id, recipe_id, name, json.dumps(ingredients), output_item, output_quantity),
            )
        except sqlite3.IntegrityError:
            return conflict("recipe already exists")

    return JsonResponse(
        _recipe_response(recipe_id, name, ingredients, output_item, output_quantity),
        status=201,
    )


@csrf_exempt
def list_recipes(request, id):
    """GET /v1/play/campaigns/{id}/recipes"""
    bad = require_method(request, "GET")
    if bad:
        return bad

    actor, campaign, err = require_play_campaign_member_or_owner(request, id)
    if err is not None:
        return err

    with db_conn() as conn:
        rows = conn.execute(
            "SELECT recipe_id, name, ingredients_json, output_item, output_quantity "
            "FROM play_recipes WHERE campaign_id = ? ORDER BY rowid ASC",
            (id,),
        ).fetchall()

    recipes = [
        _recipe_response(
            row["recipe_id"],
            row["name"],
            json.loads(row["ingredients_json"]),
            row["output_item"],
            row["output_quantity"],
        )
        for row in rows
    ]

    return JsonResponse({"recipes": recipes})


@csrf_exempt
def craft_recipe(request, id, recipe_id):
    """POST /v1/play/campaigns/{id}/recipes/{recipe_id}/craft"""
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
        if not isinstance(character_id, str) or not character_id:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    with db_conn() as conn:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (id,)
        ).fetchone()
        if campaign is None:
            return not_found("campaign not found")

        recipe = conn.execute(
            "SELECT recipe_id, name, ingredients_json, output_item, output_quantity "
            "FROM play_recipes WHERE campaign_id = ? AND recipe_id = ?",
            (id, recipe_id),
        ).fetchone()
        if recipe is None:
            return not_found("recipe not found")

        member = conn.execute(
            "SELECT character_id, owner FROM play_campaign_members "
            "WHERE campaign_id = ? AND character_id = ?",
            (id, character_id),
        ).fetchone()
        if member is None:
            return not_found("character not found")

        if actor["role"] == "dm" or actor["username"] != member["owner"]:
            return forbidden()

        ingredients = json.loads(recipe["ingredients_json"])

        for item_id, quantity in ingredients.items():
            row = conn.execute(
                "SELECT quantity FROM play_character_inventory "
                "WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
                (id, character_id, item_id),
            ).fetchone()
            if row is None or row["quantity"] < quantity:
                return conflict("insufficient ingredients")

        for item_id, quantity in ingredients.items():
            _remove_play_inventory_item(conn, id, character_id, item_id, quantity)

        _add_play_inventory_item(
            conn, id, character_id, recipe["output_item"], recipe["output_quantity"]
        )

    return JsonResponse(
        {
            "character_id": character_id,
            "recipe_id": recipe_id,
            "output_item": recipe["output_item"],
            "output_quantity": recipe["output_quantity"],
        },
        status=201,
    )
