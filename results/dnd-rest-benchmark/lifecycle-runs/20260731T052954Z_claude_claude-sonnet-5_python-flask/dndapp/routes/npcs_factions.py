"""Campaign factions, NPCs, and their aggregate relationship state."""

from flask import Blueprint, jsonify, request

from ..db import get_db
from ..validation import valid_int, valid_nonempty_str

bp = Blueprint("npcs_factions", __name__)


@bp.post("/v1/campaigns/<campaign_id>/factions")
def create_faction(campaign_id):
    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id FROM campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        data = request.get_json(silent=True) or {}
        faction_id = data.get("id")
        name = data.get("name")
        stance = data.get("stance")

        if not isinstance(faction_id, str) or not faction_id:
            return jsonify(error="invalid id"), 400
        if not valid_nonempty_str(name):
            return jsonify(error="invalid name"), 400
        if not valid_nonempty_str(stance):
            return jsonify(error="invalid stance"), 400

        existing = conn.execute(
            "SELECT id FROM factions WHERE campaign_id = ? AND id = ?",
            (campaign_id, faction_id),
        ).fetchone()
        if existing is not None:
            return jsonify(error="faction already exists"), 409

        conn.execute(
            "INSERT INTO factions (campaign_id, id, name, stance) VALUES (?, ?, ?, ?)",
            (campaign_id, faction_id, name, stance),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify(id=faction_id, name=name, stance=stance), 201


@bp.post("/v1/campaigns/<campaign_id>/npcs")
def create_npc(campaign_id):
    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id FROM campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        data = request.get_json(silent=True) or {}
        npc_id = data.get("id")
        name = data.get("name")
        faction_id = data.get("faction_id")
        disposition = data.get("disposition")

        if not isinstance(npc_id, str) or not npc_id:
            return jsonify(error="invalid id"), 400
        if not valid_nonempty_str(name):
            return jsonify(error="invalid name"), 400
        if faction_id is not None and not isinstance(faction_id, str):
            return jsonify(error="invalid faction_id"), 400
        if not valid_int(disposition):
            return jsonify(error="invalid disposition"), 400

        if faction_id is not None:
            faction = conn.execute(
                "SELECT id FROM factions WHERE campaign_id = ? AND id = ?",
                (campaign_id, faction_id),
            ).fetchone()
            if faction is None:
                return jsonify(error="faction not found"), 404

        existing = conn.execute(
            "SELECT id FROM npcs WHERE campaign_id = ? AND id = ?",
            (campaign_id, npc_id),
        ).fetchone()
        if existing is not None:
            return jsonify(error="npc already exists"), 409

        conn.execute(
            "INSERT INTO npcs (campaign_id, id, name, faction_id, disposition) "
            "VALUES (?, ?, ?, ?, ?)",
            (campaign_id, npc_id, name, faction_id, disposition),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify(
        id=npc_id, name=name, faction_id=faction_id, disposition=disposition
    ), 201


@bp.get("/v1/campaigns/<campaign_id>/relationships")
def get_relationships(campaign_id):
    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id FROM campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        faction_count = conn.execute(
            "SELECT COUNT(*) AS c FROM factions WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()["c"]
        npc_count = conn.execute(
            "SELECT COUNT(*) AS c FROM npcs WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()["c"]
        friendly_npc_count = conn.execute(
            "SELECT COUNT(*) AS c FROM npcs n "
            "JOIN factions f ON f.campaign_id = n.campaign_id AND f.id = n.faction_id "
            "WHERE n.campaign_id = ? AND f.stance = 'friendly'",
            (campaign_id,),
        ).fetchone()["c"]
    finally:
        conn.close()

    return jsonify(
        campaign_id=campaign_id,
        factions=faction_count,
        npcs=npc_count,
        friendly_npcs=friendly_npc_count,
    )
