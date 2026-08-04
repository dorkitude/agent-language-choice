"""Campaign quest tracking: create quests, record milestone progress, summarize."""

import json

from flask import Blueprint, jsonify, request

from ..db import get_db
from ..validation import valid_nonempty_str

bp = Blueprint("quests", __name__)

VALID_STATUSES = ("active", "completed", "blocked")


def _valid_milestones(value):
    return (
        isinstance(value, list)
        and len(value) > 0
        and all(valid_nonempty_str(m) for m in value)
    )


@bp.post("/v1/campaigns/<campaign_id>/quests")
def create_quest(campaign_id):
    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id FROM campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        data = request.get_json(silent=True) or {}
        quest_id = data.get("id")
        title = data.get("title")
        status = data.get("status")
        milestones = data.get("milestones")

        if not isinstance(quest_id, str) or not quest_id:
            return jsonify(error="invalid id"), 400
        if not valid_nonempty_str(title):
            return jsonify(error="invalid title"), 400
        if status not in VALID_STATUSES:
            return jsonify(error="invalid status"), 400
        if not _valid_milestones(milestones):
            return jsonify(error="invalid milestones"), 400

        existing = conn.execute(
            "SELECT id FROM quests WHERE campaign_id = ? AND id = ?",
            (campaign_id, quest_id),
        ).fetchone()
        if existing is not None:
            return jsonify(error="quest already exists"), 409

        conn.execute(
            "INSERT INTO quests (campaign_id, id, title, status, milestones_json, completed_json) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (campaign_id, quest_id, title, status, json.dumps(milestones), json.dumps([])),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify(
        id=quest_id,
        title=title,
        status=status,
        milestones_total=len(milestones),
        milestones_done=0,
    ), 201


@bp.post("/v1/campaigns/<campaign_id>/quests/<quest_id>/progress")
def update_quest_progress(campaign_id, quest_id):
    conn = get_db()
    try:
        quest = conn.execute(
            "SELECT * FROM quests WHERE campaign_id = ? AND id = ?",
            (campaign_id, quest_id),
        ).fetchone()
        if quest is None:
            return jsonify(error="quest not found"), 404

        data = request.get_json(silent=True) or {}
        completed = data.get("completed")

        if not isinstance(completed, list) or not all(
            isinstance(m, str) for m in completed
        ):
            return jsonify(error="invalid completed"), 400

        milestones = json.loads(quest["milestones_json"])
        already_done = json.loads(quest["completed_json"])

        newly_done = set(already_done)
        for milestone in completed:
            if milestone in milestones:
                newly_done.add(milestone)

        done_list = [m for m in milestones if m in newly_done]

        conn.execute(
            "UPDATE quests SET completed_json = ? WHERE campaign_id = ? AND id = ?",
            (json.dumps(done_list), campaign_id, quest_id),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify(
        id=quest_id,
        status=quest["status"],
        milestones_total=len(milestones),
        milestones_done=len(done_list),
    )


@bp.get("/v1/campaigns/<campaign_id>/quests/summary")
def quest_summary(campaign_id):
    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id FROM campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        rows = conn.execute(
            "SELECT status FROM quests WHERE campaign_id = ?", (campaign_id,)
        ).fetchall()
    finally:
        conn.close()

    counts = {"active": 0, "completed": 0, "blocked": 0}
    for row in rows:
        if row["status"] in counts:
            counts[row["status"]] += 1

    return jsonify(
        campaign_id=campaign_id,
        active=counts["active"],
        completed=counts["completed"],
        blocked=counts["blocked"],
    )
