"""Campaign inventory tracking and character equipment assignment."""

from flask import Blueprint, jsonify, request

from ..db import get_db
from ..validation import valid_int, valid_nonempty_str, valid_slug

bp = Blueprint("inventory", __name__)


@bp.post("/v1/campaigns/<campaign_id>/inventory")
def add_inventory_item(campaign_id):
    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id FROM campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        data = request.get_json(silent=True) or {}
        item_slug = data.get("item_slug")
        quantity = data.get("quantity")
        owner = data.get("owner")

        if not valid_slug(item_slug):
            return jsonify(error="invalid item_slug"), 400
        if not valid_int(quantity) or quantity <= 0:
            return jsonify(error="invalid quantity"), 400
        if not valid_nonempty_str(owner):
            return jsonify(error="invalid owner"), 400

        existing = conn.execute(
            "SELECT quantity FROM campaign_inventory WHERE campaign_id = ? AND item_slug = ? AND owner = ?",
            (campaign_id, item_slug, owner),
        ).fetchone()

        if existing is None:
            conn.execute(
                "INSERT INTO campaign_inventory (campaign_id, item_slug, owner, quantity) "
                "VALUES (?, ?, ?, ?)",
                (campaign_id, item_slug, owner, quantity),
            )
        else:
            conn.execute(
                "UPDATE campaign_inventory SET quantity = ? "
                "WHERE campaign_id = ? AND item_slug = ? AND owner = ?",
                (existing["quantity"] + quantity, campaign_id, item_slug, owner),
            )
        conn.commit()
    finally:
        conn.close()

    return jsonify(item_slug=item_slug, quantity=quantity, owner=owner), 201


@bp.post("/v1/campaigns/<campaign_id>/characters/<character_id>/equipment")
def assign_equipment(campaign_id, character_id):
    conn = get_db()
    try:
        character = conn.execute(
            "SELECT id FROM campaign_characters WHERE campaign_id = ? AND id = ?",
            (campaign_id, character_id),
        ).fetchone()
        if character is None:
            return jsonify(error="character not found"), 404

        data = request.get_json(silent=True) or {}
        item_slug = data.get("item_slug")
        quantity = data.get("quantity")

        if not valid_slug(item_slug):
            return jsonify(error="invalid item_slug"), 400
        if not valid_int(quantity) or quantity <= 0:
            return jsonify(error="invalid quantity"), 400

        existing = conn.execute(
            "SELECT quantity FROM character_equipment "
            "WHERE campaign_id = ? AND character_id = ? AND item_slug = ?",
            (campaign_id, character_id, item_slug),
        ).fetchone()

        if existing is None:
            conn.execute(
                "INSERT INTO character_equipment (campaign_id, character_id, item_slug, quantity) "
                "VALUES (?, ?, ?, ?)",
                (campaign_id, character_id, item_slug, quantity),
            )
        else:
            conn.execute(
                "UPDATE character_equipment SET quantity = ? "
                "WHERE campaign_id = ? AND character_id = ? AND item_slug = ?",
                (existing["quantity"] + quantity, campaign_id, character_id, item_slug),
            )
        conn.commit()
    finally:
        conn.close()

    return jsonify(character_id=character_id, item_slug=item_slug, quantity=quantity), 200


@bp.get("/v1/campaigns/<campaign_id>/inventory/summary")
def inventory_summary(campaign_id):
    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id FROM campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        party_items = conn.execute(
            "SELECT COUNT(*) AS c FROM campaign_inventory WHERE campaign_id = ? AND owner = 'party'",
            (campaign_id,),
        ).fetchone()["c"]

        assigned_items = conn.execute(
            "SELECT COUNT(*) AS c FROM character_equipment WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()["c"]

        party_potions = conn.execute(
            "SELECT COALESCE(SUM(quantity), 0) AS q FROM campaign_inventory "
            "WHERE campaign_id = ? AND owner = 'party' AND item_slug = 'healing-potion'",
            (campaign_id,),
        ).fetchone()["q"]

        assigned_potions = conn.execute(
            "SELECT COALESCE(SUM(quantity), 0) AS q FROM character_equipment "
            "WHERE campaign_id = ? AND item_slug = 'healing-potion'",
            (campaign_id,),
        ).fetchone()["q"]
    finally:
        conn.close()

    return jsonify(
        campaign_id=campaign_id,
        party_items=party_items,
        assigned_items=assigned_items,
        healing_potions_available=party_potions - assigned_potions,
    )
