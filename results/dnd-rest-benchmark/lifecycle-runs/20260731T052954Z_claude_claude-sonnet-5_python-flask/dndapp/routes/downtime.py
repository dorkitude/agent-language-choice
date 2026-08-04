"""Downtime crafting: multi-day crafting projects that yield campaign inventory."""

from flask import Blueprint, jsonify, request

from ..db import get_db
from ..validation import valid_int, valid_nonempty_str, valid_slug

bp = Blueprint("downtime", __name__)


@bp.post("/v1/campaigns/<campaign_id>/downtime/crafting")
def create_crafting_project(campaign_id):
    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id FROM campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        data = request.get_json(silent=True) or {}
        project_id = data.get("id")
        character_id = data.get("character_id")
        item_slug = data.get("item_slug")
        days_required = data.get("days_required")
        cost_gp = data.get("cost_gp")

        if not valid_nonempty_str(project_id):
            return jsonify(error="invalid id"), 400
        if not valid_nonempty_str(character_id):
            return jsonify(error="invalid character_id"), 400
        if not valid_slug(item_slug):
            return jsonify(error="invalid item_slug"), 400
        if not valid_int(days_required) or days_required <= 0:
            return jsonify(error="invalid days_required"), 400
        if not valid_int(cost_gp) or cost_gp < 0:
            return jsonify(error="invalid cost_gp"), 400

        character = conn.execute(
            "SELECT id FROM campaign_characters WHERE campaign_id = ? AND id = ?",
            (campaign_id, character_id),
        ).fetchone()
        if character is None:
            return jsonify(error="character not found"), 404

        existing = conn.execute(
            "SELECT id FROM crafting_projects WHERE campaign_id = ? AND id = ?",
            (campaign_id, project_id),
        ).fetchone()
        if existing is not None:
            return jsonify(error="crafting project already exists"), 409

        conn.execute(
            "INSERT INTO crafting_projects "
            "(campaign_id, id, character_id, item_slug, days_required, days_completed, cost_gp, status) "
            "VALUES (?, ?, ?, ?, ?, 0, ?, 'active')",
            (campaign_id, project_id, character_id, item_slug, days_required, cost_gp),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify(
        id=project_id,
        character_id=character_id,
        item_slug=item_slug,
        days_required=days_required,
        days_completed=0,
        status="active",
    ), 201


@bp.post("/v1/campaigns/<campaign_id>/downtime/crafting/<project_id>/advance")
def advance_crafting_project(campaign_id, project_id):
    conn = get_db()
    try:
        project = conn.execute(
            "SELECT * FROM crafting_projects WHERE campaign_id = ? AND id = ?",
            (campaign_id, project_id),
        ).fetchone()
        if project is None:
            return jsonify(error="crafting project not found"), 404

        data = request.get_json(silent=True) or {}
        days = data.get("days")
        if not valid_int(days) or days <= 0:
            return jsonify(error="invalid days"), 400

        if project["status"] != "active":
            return jsonify(error="crafting project is not active"), 400

        days_completed = min(project["days_completed"] + days, project["days_required"])
        status = "complete" if days_completed >= project["days_required"] else "active"

        conn.execute(
            "UPDATE crafting_projects SET days_completed = ?, status = ? "
            "WHERE campaign_id = ? AND id = ?",
            (days_completed, status, campaign_id, project_id),
        )

        if status == "complete":
            existing_item = conn.execute(
                "SELECT quantity FROM campaign_inventory "
                "WHERE campaign_id = ? AND item_slug = ? AND owner = 'party'",
                (campaign_id, project["item_slug"]),
            ).fetchone()
            if existing_item is None:
                conn.execute(
                    "INSERT INTO campaign_inventory (campaign_id, item_slug, owner, quantity) "
                    "VALUES (?, ?, 'party', 1)",
                    (campaign_id, project["item_slug"]),
                )
            else:
                conn.execute(
                    "UPDATE campaign_inventory SET quantity = ? "
                    "WHERE campaign_id = ? AND item_slug = ? AND owner = 'party'",
                    (existing_item["quantity"] + 1, campaign_id, project["item_slug"]),
                )

        conn.commit()
    finally:
        conn.close()

    return jsonify(id=project_id, days_completed=days_completed, status=status)
