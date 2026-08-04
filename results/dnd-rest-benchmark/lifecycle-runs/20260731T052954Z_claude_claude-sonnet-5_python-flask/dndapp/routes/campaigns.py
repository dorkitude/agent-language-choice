"""Campaign creation plus nested characters, events, and aggregate state."""

from flask import Blueprint, jsonify, request

from ..db import get_db
from ..validation import valid_int, valid_nonempty_str

bp = Blueprint("campaigns", __name__)


@bp.post("/v1/campaigns")
def create_campaign():
    data = request.get_json(silent=True) or {}
    campaign_id = data.get("id")
    name = data.get("name")
    dm = data.get("dm")

    if not isinstance(campaign_id, str) or not campaign_id:
        return jsonify(error="invalid id"), 400
    if not valid_nonempty_str(name):
        return jsonify(error="invalid name"), 400
    if not valid_nonempty_str(dm):
        return jsonify(error="invalid dm"), 400

    conn = get_db()
    try:
        existing = conn.execute(
            "SELECT id FROM campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if existing is not None:
            return jsonify(error="campaign already exists"), 409

        conn.execute(
            "INSERT INTO campaigns (id, name, dm) VALUES (?, ?, ?)",
            (campaign_id, name, dm),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify(id=campaign_id, name=name, dm=dm), 201


@bp.post("/v1/campaigns/<campaign_id>/characters")
def add_campaign_character(campaign_id):
    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id FROM campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        data = request.get_json(silent=True) or {}
        char_id = data.get("id")
        name = data.get("name")
        level = data.get("level")
        char_class = data.get("class")

        if not isinstance(char_id, str) or not char_id:
            return jsonify(error="invalid id"), 400
        if not valid_nonempty_str(name):
            return jsonify(error="invalid name"), 400
        if not valid_int(level):
            return jsonify(error="invalid level"), 400
        if not valid_nonempty_str(char_class):
            return jsonify(error="invalid class"), 400

        existing = conn.execute(
            "SELECT id FROM campaign_characters WHERE campaign_id = ? AND id = ?",
            (campaign_id, char_id),
        ).fetchone()
        if existing is not None:
            return jsonify(error="character already exists"), 409

        conn.execute(
            "INSERT INTO campaign_characters (campaign_id, id, name, level, class) "
            "VALUES (?, ?, ?, ?, ?)",
            (campaign_id, char_id, name, level, char_class),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify(id=char_id, name=name, level=level, **{"class": char_class}), 201


@bp.post("/v1/campaigns/<campaign_id>/events")
def add_campaign_event(campaign_id):
    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id FROM campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        data = request.get_json(silent=True) or {}
        event_id = data.get("id")
        kind = data.get("kind")
        summary = data.get("summary")

        if not isinstance(event_id, str) or not event_id:
            return jsonify(error="invalid id"), 400
        if not valid_nonempty_str(kind):
            return jsonify(error="invalid kind"), 400
        if not isinstance(summary, str) or not summary:
            return jsonify(error="invalid summary"), 400

        existing = conn.execute(
            "SELECT id FROM campaign_events WHERE campaign_id = ? AND id = ?",
            (campaign_id, event_id),
        ).fetchone()
        if existing is not None:
            return jsonify(error="event already exists"), 409

        conn.execute(
            "INSERT INTO campaign_events (campaign_id, id, kind, summary) "
            "VALUES (?, ?, ?, ?)",
            (campaign_id, event_id, kind, summary),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify(id=event_id, kind=kind), 201


@bp.get("/v1/campaigns/<campaign_id>/state")
def get_campaign_state(campaign_id):
    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, name, dm FROM campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        char_rows = conn.execute(
            "SELECT id, name, level, class FROM campaign_characters WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchall()
        log_count = conn.execute(
            "SELECT COUNT(*) AS c FROM campaign_events WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()["c"]
    finally:
        conn.close()

    characters = [
        {
            "id": row["id"],
            "name": row["name"],
            "level": row["level"],
            "class": row["class"],
        }
        for row in char_rows
    ]

    return jsonify(
        id=campaign["id"],
        name=campaign["name"],
        dm=campaign["dm"],
        characters=characters,
        log_count=log_count,
    )
