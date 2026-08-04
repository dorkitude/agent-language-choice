"""Campaign session scheduling: schedule sessions, record attendance, next session."""

import json

from flask import Blueprint, jsonify, request

from ..db import get_db
from ..validation import valid_int, valid_nonempty_str

bp = Blueprint("sessions", __name__)


def _valid_agenda(value):
    return isinstance(value, list) and all(isinstance(a, str) for a in value)


def _valid_roster(value):
    return isinstance(value, list) and all(isinstance(m, str) for m in value)


@bp.post("/v1/campaigns/<campaign_id>/sessions")
def schedule_session(campaign_id):
    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id FROM campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        data = request.get_json(silent=True) or {}
        session_id = data.get("id")
        starts_at = data.get("starts_at")
        duration_minutes = data.get("duration_minutes")
        agenda = data.get("agenda")

        if not isinstance(session_id, str) or not session_id:
            return jsonify(error="invalid id"), 400
        if not valid_nonempty_str(starts_at):
            return jsonify(error="invalid starts_at"), 400
        if not valid_int(duration_minutes) or duration_minutes <= 0:
            return jsonify(error="invalid duration_minutes"), 400
        if not _valid_agenda(agenda):
            return jsonify(error="invalid agenda"), 400

        existing = conn.execute(
            "SELECT id FROM campaign_sessions WHERE campaign_id = ? AND id = ?",
            (campaign_id, session_id),
        ).fetchone()
        if existing is not None:
            return jsonify(error="session already exists"), 409

        conn.execute(
            "INSERT INTO campaign_sessions "
            "(campaign_id, id, starts_at, duration_minutes, agenda_json) "
            "VALUES (?, ?, ?, ?, ?)",
            (campaign_id, session_id, starts_at, duration_minutes, json.dumps(agenda)),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify(
        id=session_id,
        starts_at=starts_at,
        duration_minutes=duration_minutes,
        agenda_count=len(agenda),
    ), 201


@bp.post("/v1/campaigns/<campaign_id>/sessions/<session_id>/attendance")
def record_attendance(campaign_id, session_id):
    conn = get_db()
    try:
        session = conn.execute(
            "SELECT id FROM campaign_sessions WHERE campaign_id = ? AND id = ?",
            (campaign_id, session_id),
        ).fetchone()
        if session is None:
            return jsonify(error="session not found"), 404

        data = request.get_json(silent=True) or {}
        present = data.get("present")
        absent = data.get("absent")

        if not _valid_roster(present):
            return jsonify(error="invalid present"), 400
        if not _valid_roster(absent):
            return jsonify(error="invalid absent"), 400

        conn.execute(
            "INSERT INTO session_attendance (campaign_id, session_id, present_json, absent_json) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(campaign_id, session_id) DO UPDATE SET "
            "present_json = excluded.present_json, absent_json = excluded.absent_json",
            (campaign_id, session_id, json.dumps(present), json.dumps(absent)),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify(
        session_id=session_id,
        present_count=len(present),
        absent_count=len(absent),
    )


@bp.get("/v1/campaigns/<campaign_id>/sessions/next")
def next_session(campaign_id):
    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id FROM campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        row = conn.execute(
            "SELECT id, starts_at, agenda_json FROM campaign_sessions "
            "WHERE campaign_id = ? ORDER BY starts_at ASC LIMIT 1",
            (campaign_id,),
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        return jsonify(error="no sessions scheduled"), 404

    agenda = json.loads(row["agenda_json"])

    return jsonify(
        id=row["id"],
        starts_at=row["starts_at"],
        agenda_count=len(agenda),
    )
