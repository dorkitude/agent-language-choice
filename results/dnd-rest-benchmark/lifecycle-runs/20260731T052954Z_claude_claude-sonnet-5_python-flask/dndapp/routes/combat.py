"""Combat-session lifecycle: create, add condition, advance turn."""

from flask import Blueprint, jsonify, request

from ..combat import build_order, load_session, save_session, session_response
from ..db import get_db

bp = Blueprint("combat", __name__)


@bp.post("/v1/combat/sessions")
def create_combat_session():
    data = request.get_json(silent=True) or {}
    session_id = data.get("id")
    combatants = data.get("combatants")

    if not isinstance(session_id, str) or not session_id:
        return jsonify(error="invalid id"), 400
    if not isinstance(combatants, list) or not combatants:
        return jsonify(error="invalid combatants"), 400

    try:
        scored = build_order(combatants)
    except (KeyError, TypeError):
        return jsonify(error="invalid combatants"), 400

    conn = get_db()
    try:
        if load_session(conn, session_id) is not None:
            return jsonify(error="session already exists"), 400

        session = {
            "id": session_id,
            "round": 1,
            "turn_index": 0,
            "order": scored,
            "conditions": {},
        }
        save_session(conn, session)
    finally:
        conn.close()

    return jsonify(session_response(session))


@bp.post("/v1/combat/sessions/<session_id>/conditions")
def add_condition(session_id):
    conn = get_db()
    try:
        session = load_session(conn, session_id)
        if session is None:
            return jsonify(error="session not found"), 404

        data = request.get_json(silent=True) or {}
        target = data.get("target")
        condition = data.get("condition")
        duration_rounds = data.get("duration_rounds")

        if not isinstance(target, str) or not target:
            return jsonify(error="invalid target"), 400
        if target not in {c["name"] for c in session["order"]}:
            return jsonify(error="invalid target"), 400
        if not isinstance(condition, str) or not condition:
            return jsonify(error="invalid condition"), 400
        if (
            not isinstance(duration_rounds, int)
            or isinstance(duration_rounds, bool)
            or duration_rounds <= 0
        ):
            return jsonify(error="invalid duration_rounds"), 400

        conditions = session["conditions"].setdefault(target, [])
        conditions.append({"condition": condition, "remaining_rounds": duration_rounds})
        save_session(conn, session)

        return jsonify(target=target, conditions=conditions)
    finally:
        conn.close()


@bp.post("/v1/combat/sessions/<session_id>/advance")
def advance_combat(session_id):
    conn = get_db()
    try:
        session = load_session(conn, session_id)
        if session is None:
            return jsonify(error="session not found"), 404

        order = session["order"]
        next_index = session["turn_index"] + 1
        if next_index >= len(order):
            next_index = 0
            session["round"] += 1
        session["turn_index"] = next_index

        active_name = order[next_index]["name"]
        remaining = []
        for cond in session["conditions"].get(active_name, []):
            cond["remaining_rounds"] -= 1
            if cond["remaining_rounds"] > 0:
                remaining.append(cond)
        if active_name in session["conditions"]:
            session["conditions"][active_name] = remaining

        save_session(conn, session)

        active = {"name": active_name, "score": order[next_index]["score"]}

        return jsonify(
            id=session["id"],
            round=session["round"],
            turn_index=session["turn_index"],
            active=active,
            conditions=session["conditions"],
        )
    finally:
        conn.close()
