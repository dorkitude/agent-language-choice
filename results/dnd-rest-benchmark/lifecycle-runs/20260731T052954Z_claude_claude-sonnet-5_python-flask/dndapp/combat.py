"""Combat-session persistence and initiative-ordering logic.

A combat session's `order`/`conditions` are stored as JSON blobs rather than
normalized rows: the whole session is always read and rewritten together, so
there is no benefit to relational decomposition and JSON keeps the
save/load pair trivial.
"""

import json


def build_order(combatants):
    scored = []
    for c in combatants:
        name = c["name"]
        dex = c["dex"]
        roll = c["roll"]
        score = roll + dex
        scored.append({"name": name, "dex": dex, "score": score})
    scored.sort(key=lambda c: (-c["score"], -c["dex"], c["name"]))
    return scored


def load_session(conn, session_id):
    row = conn.execute(
        "SELECT id, round, turn_index, order_json, conditions_json FROM combat_sessions WHERE id = ?",
        (session_id,),
    ).fetchone()
    if row is None:
        return None
    return {
        "id": row["id"],
        "round": row["round"],
        "turn_index": row["turn_index"],
        "order": json.loads(row["order_json"]),
        "conditions": json.loads(row["conditions_json"]),
    }


def save_session(conn, session):
    conn.execute(
        """
        INSERT INTO combat_sessions (id, round, turn_index, order_json, conditions_json)
        VALUES (:id, :round, :turn_index, :order_json, :conditions_json)
        ON CONFLICT(id) DO UPDATE SET
            round=excluded.round,
            turn_index=excluded.turn_index,
            order_json=excluded.order_json,
            conditions_json=excluded.conditions_json
        """,
        {
            "id": session["id"],
            "round": session["round"],
            "turn_index": session["turn_index"],
            "order_json": json.dumps(session["order"]),
            "conditions_json": json.dumps(session["conditions"]),
        },
    )
    conn.commit()


def session_response(session):
    order = [{"name": c["name"], "score": c["score"]} for c in session["order"]]
    active = order[session["turn_index"]]
    return {
        "id": session["id"],
        "round": session["round"],
        "turn_index": session["turn_index"],
        "active": active,
        "order": order,
    }
