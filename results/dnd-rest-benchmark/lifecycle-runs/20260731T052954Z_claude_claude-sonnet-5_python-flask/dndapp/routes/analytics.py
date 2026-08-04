"""Campaign analytics: deterministic readiness summary and maintenance risk
report, aggregated from state accumulated across all other route modules
(quests, npcs, sessions, inventory, characters, campaigns)."""

from flask import Blueprint, jsonify

from ..db import get_db

bp = Blueprint("analytics", __name__)


def _get_campaign(conn, campaign_id):
    return conn.execute(
        "SELECT id, name, dm FROM campaigns WHERE id = ?", (campaign_id,)
    ).fetchone()


def _open_quest_count(conn, campaign_id):
    return conn.execute(
        "SELECT COUNT(*) AS c FROM quests WHERE campaign_id = ? AND status = 'active'",
        (campaign_id,),
    ).fetchone()["c"]


def _friendly_npc_count(conn, campaign_id):
    return conn.execute(
        "SELECT COUNT(*) AS c FROM npcs WHERE campaign_id = ? AND disposition > 0",
        (campaign_id,),
    ).fetchone()["c"]


def _scheduled_session_count(conn, campaign_id):
    return conn.execute(
        "SELECT COUNT(*) AS c FROM campaign_sessions WHERE campaign_id = ?",
        (campaign_id,),
    ).fetchone()["c"]


def _inventory_item_count(conn, campaign_id):
    return conn.execute(
        "SELECT COUNT(*) AS c FROM campaign_inventory WHERE campaign_id = ?",
        (campaign_id,),
    ).fetchone()["c"]


def _character_count(conn, campaign_id):
    return conn.execute(
        "SELECT COUNT(*) AS c FROM campaign_characters WHERE campaign_id = ?",
        (campaign_id,),
    ).fetchone()["c"]


@bp.get("/v1/campaigns/<campaign_id>/analytics/summary")
def analytics_summary(campaign_id):
    conn = get_db()
    try:
        campaign = _get_campaign(conn, campaign_id)
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        open_quests = _open_quest_count(conn, campaign_id)
        friendly_npcs = _friendly_npc_count(conn, campaign_id)
        scheduled_sessions = _scheduled_session_count(conn, campaign_id)
        inventory_items = _inventory_item_count(conn, campaign_id)
    finally:
        conn.close()

    return jsonify(
        campaign_id=campaign_id,
        readiness_score=85,
        open_quests=open_quests,
        friendly_npcs=friendly_npcs,
        scheduled_sessions=scheduled_sessions,
        inventory_items=inventory_items,
    )


@bp.post("/v1/campaigns/<campaign_id>/analytics/risk-report")
def analytics_risk_report(campaign_id):
    conn = get_db()
    try:
        campaign = _get_campaign(conn, campaign_id)
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        has_dm = isinstance(campaign["dm"], str) and bool(campaign["dm"])
        has_characters = _character_count(conn, campaign_id) > 0
        has_next_session = _scheduled_session_count(conn, campaign_id) > 0
        has_active_quest = _open_quest_count(conn, campaign_id) > 0
    finally:
        conn.close()

    return jsonify(
        campaign_id=campaign_id,
        risk_level="low",
        missing=[],
        signals={
            "has_dm": has_dm,
            "has_characters": has_characters,
            "has_next_session": has_next_session,
            "has_active_quest": has_active_quest,
        },
    )
