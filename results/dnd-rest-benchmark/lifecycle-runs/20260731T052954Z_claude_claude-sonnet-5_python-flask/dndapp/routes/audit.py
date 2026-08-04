"""Deterministic audit log and export summaries for campaign state."""

from flask import Blueprint, jsonify

from ..db import SCHEMA_VERSION, get_db

bp = Blueprint("audit", __name__)


def _count(conn, table, campaign_id):
    return conn.execute(
        f"SELECT COUNT(*) AS c FROM {table} WHERE campaign_id = ?",
        (campaign_id,),
    ).fetchone()["c"]


@bp.get("/v1/campaigns/<campaign_id>/audit")
def get_campaign_audit(campaign_id):
    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id FROM campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        events = _count(conn, "campaign_events", campaign_id)
        quests = _count(conn, "quests", campaign_id)
        npcs = _count(conn, "npcs", campaign_id)
        sessions = _count(conn, "campaign_sessions", campaign_id)
    finally:
        conn.close()

    return jsonify(
        campaign_id=campaign_id,
        events=events,
        quests=quests,
        npcs=npcs,
        sessions=sessions,
    )


@bp.get("/v1/campaigns/<campaign_id>/export")
def export_campaign(campaign_id):
    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, name FROM campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        characters = _count(conn, "campaign_characters", campaign_id)
        quests = _count(conn, "quests", campaign_id)
        npcs = _count(conn, "npcs", campaign_id)
        inventory_items = _count(conn, "campaign_inventory", campaign_id)
        sessions = _count(conn, "campaign_sessions", campaign_id)
    finally:
        conn.close()

    return jsonify(
        campaign_id=campaign["id"],
        name=campaign["name"],
        characters=characters,
        quests=quests,
        npcs=npcs,
        inventory_items=inventory_items,
        sessions=sessions,
        schema_version=SCHEMA_VERSION,
    )
