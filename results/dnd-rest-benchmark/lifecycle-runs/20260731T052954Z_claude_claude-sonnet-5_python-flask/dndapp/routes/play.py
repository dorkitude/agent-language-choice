"""Protected campaign-play surface, gated by a session bearer token."""

import json
from functools import wraps

from flask import Blueprint, jsonify, request

from ..db import get_db
from ..rules import (
    HIT_DICE,
    VALID_BACKGROUNDS,
    VALID_RACES,
    ability_modifier,
    average_hit_die_value,
    hp_max_at_level1,
    max_prepared_spells,
    PREPARED_SPELL_ABILITY,
    proficiency_bonus,
    spell_known_by_class,
    spell_slots_at_level,
    SPELLCASTING_CLASSES,
)
from ..validation import valid_int, valid_int_in_range, valid_nonempty_str, valid_slug

ABILITY_KEYS = ("str", "dex", "con", "int", "wis", "cha")

VALID_DELEGATION_POWERS = frozenset({"narrate"})

VALID_SKILLS = frozenset(
    {
        "acrobatics",
        "animal_handling",
        "arcana",
        "athletics",
        "deception",
        "history",
        "insight",
        "intimidation",
        "investigation",
        "medicine",
        "nature",
        "perception",
        "performance",
        "persuasion",
        "religion",
        "sleight_of_hand",
        "stealth",
        "survival",
    }
)

MODIFIER_COLUMNS = {
    "str": "str_modifier",
    "dex": "dex_modifier",
    "con": "con_modifier",
    "int": "int_modifier",
    "wis": "wis_modifier",
    "cha": "cha_modifier",
}

bp = Blueprint("play", __name__)


class AuthError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


def authenticate():
    """Return (username, role) for the bearer actor.

    Raises AuthError(401) when the credential is missing/malformed, and
    AuthError(403) when it is well-formed but names an unknown user.
    """
    header = request.headers.get("Authorization", "")
    prefix = "Bearer session-"
    if not header:
        raise AuthError(401, "authentication required")
    if not header.startswith(prefix):
        raise AuthError(401, "invalid authentication")
    username = header[len(prefix):]
    if not username:
        raise AuthError(401, "invalid authentication")

    conn = get_db()
    try:
        row = conn.execute(
            "SELECT username, role FROM users WHERE username = ?", (username,)
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        raise AuthError(403, "not a campaign member")
    return row["username"], row["role"]


def require_auth(view):
    """Resolve the bearer actor and pass (username, role) as the view's
    first two arguments; short-circuits with the AuthError's status/body
    when authentication fails, so every route below stays free of the
    try/except boilerplate.
    """

    @wraps(view)
    def wrapper(*args, **kwargs):
        try:
            username, role = authenticate()
        except AuthError as exc:
            return jsonify(error=exc.message), exc.status
        return view(username, role, *args, **kwargs)

    return wrapper


def next_sequence(conn, campaign_id):
    """Next play_events.sequence for a campaign (1-based, per-campaign)."""
    last_sequence = conn.execute(
        "SELECT MAX(sequence) AS s FROM play_events WHERE campaign_id = ?",
        (campaign_id,),
    ).fetchone()["s"]
    return (last_sequence or 0) + 1


def serialize_events(events):
    """Oldest-first event dicts from a newest-first DB row set."""
    return [
        {
            "sequence": event["sequence"],
            "kind": event["kind"],
            "actor": event["actor"],
            "text": event["text"],
        }
        for event in reversed(events)
    ]


@bp.post("/v1/play/campaigns")
@require_auth
def create_play_campaign(username, role):
    if role != "dm":
        return jsonify(error="forbidden"), 403

    data = request.get_json(silent=True) or {}
    campaign_id = data.get("id")
    name = data.get("name")
    max_players = data.get("max_players")

    if not isinstance(campaign_id, str) or not campaign_id:
        return jsonify(error="invalid id"), 400
    if not valid_nonempty_str(name):
        return jsonify(error="invalid name"), 400
    if not valid_int(max_players):
        return jsonify(error="invalid max_players"), 400

    conn = get_db()
    try:
        existing = conn.execute(
            "SELECT id FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if existing is not None:
            return jsonify(error="campaign already exists"), 409

        conn.execute(
            "INSERT INTO play_campaigns (id, name, owner, status, max_players) "
            "VALUES (?, ?, ?, ?, ?)",
            (campaign_id, name, username, "lobby", max_players),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify(
        id=campaign_id,
        name=name,
        owner=username,
        status="lobby",
        max_players=max_players,
    ), 201


@bp.post("/v1/play/campaigns/<campaign_id>/members")
@require_auth
def join_play_campaign(username, role, campaign_id):
    if role != "player":
        return jsonify(error="forbidden"), 403

    data = request.get_json(silent=True) or {}
    character_id = data.get("character_id")
    name = data.get("name")
    char_class = data.get("class")

    if not isinstance(character_id, str) or not character_id:
        return jsonify(error="invalid character_id"), 400
    if not valid_nonempty_str(name):
        return jsonify(error="invalid name"), 400
    if not valid_nonempty_str(char_class):
        return jsonify(error="invalid class"), 400

    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, max_players FROM play_campaigns WHERE id = ?",
            (campaign_id,),
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        existing_membership = conn.execute(
            "SELECT username FROM play_members WHERE campaign_id = ? AND username = ?",
            (campaign_id, username),
        ).fetchone()
        existing_character = conn.execute(
            "SELECT character_id FROM play_members WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, character_id),
        ).fetchone()
        member_count = conn.execute(
            "SELECT COUNT(*) AS c FROM play_members WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()["c"]

        if (
            existing_membership is not None
            or existing_character is not None
            or member_count >= campaign["max_players"]
        ):
            return jsonify(error="cannot join campaign"), 409

        conn.execute(
            "INSERT INTO play_members (campaign_id, username, character_id, name, class) "
            "VALUES (?, ?, ?, ?, ?)",
            (campaign_id, username, character_id, name, char_class),
        )
        conn.execute(
            "INSERT INTO play_character_owners (campaign_id, character_id, owner, class) "
            "VALUES (?, ?, ?, ?)",
            (campaign_id, character_id, username, char_class),
        )
        conn.execute(
            "INSERT INTO play_character_currency (campaign_id, character_id, gold) "
            "VALUES (?, ?, ?)",
            (campaign_id, character_id, 10),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify(
        username=username,
        character_id=character_id,
        name=name,
        **{"class": char_class},
    ), 201


@bp.post("/v1/play/campaigns/<campaign_id>/start")
@require_auth
def start_play_campaign(username, _role, campaign_id):
    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner, status FROM play_campaigns WHERE id = ?",
            (campaign_id,),
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        if campaign["owner"] != username:
            return jsonify(error="forbidden"), 403

        members = conn.execute(
            "SELECT username FROM play_members WHERE campaign_id = ? ORDER BY rowid",
            (campaign_id,),
        ).fetchall()

        if campaign["status"] != "lobby" or len(members) < 2:
            return jsonify(error="cannot start campaign"), 409

        current_actor = members[0]["username"]
        turn_number = 1

        conn.execute(
            "UPDATE play_campaigns SET status = ?, current_actor = ?, turn_number = ? "
            "WHERE id = ?",
            ("active", current_actor, turn_number, campaign_id),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify(
        id=campaign_id,
        status="active",
        current_actor=current_actor,
        turn_number=turn_number,
    ), 200


@bp.post("/v1/play/campaigns/<campaign_id>/narrations")
@require_auth
def narrate_play_campaign(username, role, campaign_id):
    data = request.get_json(silent=True) or {}
    text = data.get("text")

    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()

        is_delegate = False
        if campaign is not None and role != "dm":
            delegation = conn.execute(
                "SELECT powers FROM play_delegations "
                "WHERE campaign_id = ? AND username = ? AND active = 1",
                (campaign_id, username),
            ).fetchone()
            is_delegate = (
                delegation is not None
                and "narrate" in json.loads(delegation["powers"])
            )

        if role != "dm" and not is_delegate:
            return jsonify(error="forbidden"), 403

        if not valid_nonempty_str(text):
            return jsonify(error="invalid text"), 400

        if campaign is None:
            return jsonify(error="campaign not found"), 404

        if not is_delegate and campaign["owner"] != username:
            return jsonify(error="forbidden"), 403

        sequence = next_sequence(conn, campaign_id)

        conn.execute(
            "INSERT INTO play_events (campaign_id, sequence, kind, actor, text) "
            "VALUES (?, ?, ?, ?, ?)",
            (campaign_id, sequence, "narration", username, text),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify(
        sequence=sequence,
        kind="narration",
        actor=username,
        text=text,
    ), 201


@bp.post("/v1/play/campaigns/<campaign_id>/actions")
@require_auth
def submit_play_campaign_action(username, _role, campaign_id):
    data = request.get_json(silent=True) or {}
    action_type = data.get("type")
    text = data.get("text")

    if not valid_nonempty_str(action_type):
        return jsonify(error="invalid type"), 400
    if not valid_nonempty_str(text):
        return jsonify(error="invalid text"), 400

    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner, current_actor FROM play_campaigns WHERE id = ?",
            (campaign_id,),
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        member = conn.execute(
            "SELECT username FROM play_members WHERE campaign_id = ? AND username = ?",
            (campaign_id, username),
        ).fetchone()

        if member is None:
            if username == campaign["owner"]:
                return jsonify(error="cannot submit action"), 409
            return jsonify(error="not a campaign member"), 403

        if campaign["current_actor"] != username:
            return jsonify(error="cannot submit action"), 409

        sequence = next_sequence(conn, campaign_id)

        conn.execute(
            "INSERT INTO play_events (campaign_id, sequence, kind, actor, type, text) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (campaign_id, sequence, "action", username, action_type, text),
        )
        conn.execute(
            "UPDATE play_campaigns SET current_actor = ? WHERE id = ?",
            ("dm", campaign_id),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify(
        sequence=sequence,
        kind="action",
        actor=username,
        type=action_type,
        text=text,
        next_actor="dm",
    ), 201


@bp.post("/v1/play/campaigns/<campaign_id>/resolutions")
@require_auth
def resolve_play_campaign(username, _role, campaign_id):
    data = request.get_json(silent=True) or {}
    text = data.get("text")

    if not valid_nonempty_str(text):
        return jsonify(error="invalid text"), 400

    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner, current_actor, turn_number FROM play_campaigns WHERE id = ?",
            (campaign_id,),
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        member = conn.execute(
            "SELECT username FROM play_members WHERE campaign_id = ? AND username = ?",
            (campaign_id, username),
        ).fetchone()

        if username != campaign["owner"] and member is None:
            return jsonify(error="not a campaign member"), 403

        if username != campaign["owner"]:
            return jsonify(error="cannot resolve"), 409

        if campaign["current_actor"] != "dm":
            return jsonify(error="cannot resolve"), 409

        members = conn.execute(
            "SELECT username FROM play_members WHERE campaign_id = ? ORDER BY rowid",
            (campaign_id,),
        ).fetchall()
        member_usernames = [m["username"] for m in members]

        last_action = conn.execute(
            "SELECT actor FROM play_events WHERE campaign_id = ? "
            "AND kind IN ('action', 'travel') "
            "ORDER BY sequence DESC LIMIT 1",
            (campaign_id,),
        ).fetchone()

        if last_action is not None and last_action["actor"] in member_usernames:
            idx = member_usernames.index(last_action["actor"])
            next_actor = member_usernames[(idx + 1) % len(member_usernames)]
        else:
            next_actor = member_usernames[0]

        sequence = next_sequence(conn, campaign_id)
        turn_number = campaign["turn_number"] + 1

        conn.execute(
            "INSERT INTO play_events (campaign_id, sequence, kind, actor, text) "
            "VALUES (?, ?, ?, ?, ?)",
            (campaign_id, sequence, "resolution", username, text),
        )
        conn.execute(
            "UPDATE play_campaigns SET current_actor = ?, turn_number = ? WHERE id = ?",
            (next_actor, turn_number, campaign_id),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify(
        sequence=sequence,
        kind="resolution",
        actor=username,
        text=text,
        next_actor=next_actor,
        turn_number=turn_number,
    ), 201


@bp.get("/v1/play/campaigns/<campaign_id>/turn")
@require_auth
def get_play_campaign_turn(username, _role, campaign_id):
    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner, status, current_actor, turn_number "
            "FROM play_campaigns WHERE id = ?",
            (campaign_id,),
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        is_member = conn.execute(
            "SELECT 1 FROM play_members WHERE campaign_id = ? AND username = ?",
            (campaign_id, username),
        ).fetchone()

        if campaign["owner"] != username and is_member is None:
            return jsonify(error="not a campaign member"), 403

        members = conn.execute(
            "SELECT username FROM play_members WHERE campaign_id = ? ORDER BY rowid",
            (campaign_id,),
        ).fetchall()
    finally:
        conn.close()

    phase = "dm" if campaign["current_actor"] == "dm" else "player"

    queue = []
    for member in members:
        queue.append(member["username"])
        queue.append("dm")

    return jsonify(
        campaign_id=campaign_id,
        current_actor=campaign["current_actor"],
        phase=phase,
        turn_number=campaign["turn_number"],
        queue=queue,
        overdue=False,
        logical_deadline=campaign["turn_number"] + 1,
    ), 200


@bp.post("/v1/play/campaigns/<campaign_id>/turn/nudge")
@require_auth
def nudge_play_campaign_turn(username, _role, campaign_id):
    data = request.get_json(silent=True) or {}
    message = data.get("message")

    if not valid_nonempty_str(message):
        return jsonify(error="invalid message"), 400

    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner, current_actor, nudge_count FROM play_campaigns WHERE id = ?",
            (campaign_id,),
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        if campaign["owner"] != username:
            return jsonify(error="forbidden"), 403

        nudge_count = campaign["nudge_count"] + 1

        conn.execute(
            "UPDATE play_campaigns SET nudge_count = ? WHERE id = ?",
            (nudge_count, campaign_id),
        )

        sequence = next_sequence(conn, campaign_id)

        conn.execute(
            "INSERT INTO play_events (campaign_id, sequence, kind, actor, text) "
            "VALUES (?, ?, ?, ?, ?)",
            (campaign_id, sequence, "nudge", username, message),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify(
        actor=username,
        target=campaign["current_actor"],
        message=message,
        nudge_count=nudge_count,
    ), 201


@bp.get("/v1/play/campaigns/<campaign_id>/my-turn")
@require_auth
def get_play_campaign_my_turn(username, role, campaign_id):
    if role != "player":
        return jsonify(error="forbidden"), 403

    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, current_actor FROM play_campaigns WHERE id = ?",
            (campaign_id,),
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        member = conn.execute(
            "SELECT character_id, name FROM play_members "
            "WHERE campaign_id = ? AND username = ?",
            (campaign_id, username),
        ).fetchone()

        if member is None:
            return jsonify(error="not a campaign member"), 403

        events = conn.execute(
            "SELECT sequence, kind, actor, text FROM play_events "
            "WHERE campaign_id = ? ORDER BY sequence DESC LIMIT 10",
            (campaign_id,),
        ).fetchall()
    finally:
        conn.close()

    return jsonify(
        is_my_turn=campaign["current_actor"] == username,
        current_actor=campaign["current_actor"],
        character={"id": member["character_id"], "name": member["name"]},
        recent_events=serialize_events(events),
    ), 200


@bp.get("/v1/play/campaigns/<campaign_id>/document")
@require_auth
def get_play_campaign_document(username, _role, campaign_id):
    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner, story, dm_notes FROM play_campaigns WHERE id = ?",
            (campaign_id,),
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        is_member = conn.execute(
            "SELECT 1 FROM play_members WHERE campaign_id = ? AND username = ?",
            (campaign_id, username),
        ).fetchone()
    finally:
        conn.close()

    if campaign["owner"] != username and is_member is None:
        return jsonify(error="not a campaign member"), 403

    if campaign["owner"] == username:
        return jsonify(story=campaign["story"], dm_notes=campaign["dm_notes"]), 200

    return jsonify(story=campaign["story"]), 200


@bp.put("/v1/play/campaigns/<campaign_id>/document")
@require_auth
def put_play_campaign_document(username, _role, campaign_id):
    data = request.get_json(silent=True) or {}
    story = data.get("story")
    dm_notes = data.get("dm_notes")

    if not isinstance(story, str):
        return jsonify(error="invalid story"), 400
    if not isinstance(dm_notes, str):
        return jsonify(error="invalid dm_notes"), 400

    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        if campaign["owner"] != username:
            return jsonify(error="forbidden"), 403

        conn.execute(
            "UPDATE play_campaigns SET story = ?, dm_notes = ? WHERE id = ?",
            (story, dm_notes, campaign_id),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify(story=story, dm_notes=dm_notes), 200


@bp.post("/v1/play/campaigns/<campaign_id>/scenes")
@require_auth
def create_play_campaign_scene(username, _role, campaign_id):
    data = request.get_json(silent=True) or {}
    scene_id = data.get("id")
    name = data.get("name")

    if not isinstance(scene_id, str) or not scene_id:
        return jsonify(error="invalid id"), 400
    if not valid_nonempty_str(name):
        return jsonify(error="invalid name"), 400

    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        if campaign["owner"] != username:
            return jsonify(error="forbidden"), 403

        existing = conn.execute(
            "SELECT id FROM play_scenes WHERE campaign_id = ? AND id = ?",
            (campaign_id, scene_id),
        ).fetchone()
        if existing is not None:
            return jsonify(error="scene already exists"), 409

        conn.execute(
            "INSERT INTO play_scenes (campaign_id, id, name, status) VALUES (?, ?, ?, ?)",
            (campaign_id, scene_id, name, "open"),
        )

        sequence = next_sequence(conn, campaign_id)
        conn.execute(
            "INSERT INTO play_events (campaign_id, sequence, kind, actor, text) "
            "VALUES (?, ?, ?, ?, ?)",
            (campaign_id, sequence, "scene", username, scene_id),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify(id=scene_id, name=name, status="open"), 201


@bp.post("/v1/play/campaigns/<campaign_id>/scenes/<scene_id>/enter")
@require_auth
def enter_play_campaign_scene(username, _role, campaign_id, scene_id):
    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        if campaign["owner"] != username:
            return jsonify(error="forbidden"), 403

        scene = conn.execute(
            "SELECT id, name, status FROM play_scenes WHERE campaign_id = ? AND id = ?",
            (campaign_id, scene_id),
        ).fetchone()
        if scene is None:
            return jsonify(error="scene not found"), 404

        if scene["status"] != "open":
            return jsonify(error="cannot enter closed scene"), 409

        conn.execute(
            "UPDATE play_campaigns SET current_scene_id = ? WHERE id = ?",
            (scene_id, campaign_id),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify(current_scene_id=scene_id, name=scene["name"]), 200


@bp.post("/v1/play/campaigns/<campaign_id>/scenes/<scene_id>/close")
@require_auth
def close_play_campaign_scene(username, _role, campaign_id, scene_id):
    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        if campaign["owner"] != username:
            return jsonify(error="forbidden"), 403

        scene = conn.execute(
            "SELECT id FROM play_scenes WHERE campaign_id = ? AND id = ?",
            (campaign_id, scene_id),
        ).fetchone()
        if scene is None:
            return jsonify(error="scene not found"), 404

        conn.execute(
            "UPDATE play_scenes SET status = ? WHERE campaign_id = ? AND id = ?",
            ("closed", campaign_id, scene_id),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify(id=scene_id, status="closed"), 200


@bp.get("/v1/play/campaigns/<campaign_id>/scenes/current")
@require_auth
def get_play_campaign_current_scene(username, _role, campaign_id):
    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner, current_scene_id FROM play_campaigns WHERE id = ?",
            (campaign_id,),
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        is_member = conn.execute(
            "SELECT 1 FROM play_members WHERE campaign_id = ? AND username = ?",
            (campaign_id, username),
        ).fetchone()

        if campaign["owner"] != username and is_member is None:
            return jsonify(error="not a campaign member"), 403

        if campaign["current_scene_id"] is None:
            return jsonify(error="no current scene"), 404

        scene = conn.execute(
            "SELECT id, name, status FROM play_scenes WHERE campaign_id = ? AND id = ?",
            (campaign_id, campaign["current_scene_id"]),
        ).fetchone()
    finally:
        conn.close()

    if scene is None or scene["status"] != "open":
        return jsonify(error="no current scene"), 404

    return jsonify(id=scene["id"], name=scene["name"], status=scene["status"]), 200


@bp.get("/v1/play/campaigns/<campaign_id>/gm/status")
@require_auth
def get_play_campaign_gm_status(username, _role, campaign_id):
    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner, current_actor FROM play_campaigns WHERE id = ?",
            (campaign_id,),
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        if campaign["owner"] != username:
            return jsonify(error="forbidden"), 403

        members = conn.execute(
            "SELECT username, character_id, name, class FROM play_members "
            "WHERE campaign_id = ? ORDER BY rowid",
            (campaign_id,),
        ).fetchall()

        events = conn.execute(
            "SELECT sequence, kind, actor, text FROM play_events "
            "WHERE campaign_id = ? ORDER BY sequence DESC LIMIT 10",
            (campaign_id,),
        ).fetchall()
    finally:
        conn.close()

    party = [
        {
            "username": member["username"],
            "character_id": member["character_id"],
            "name": member["name"],
            "class": member["class"],
        }
        for member in members
    ]

    return jsonify(
        needs_attention=campaign["current_actor"] == campaign["owner"],
        current_actor=campaign["current_actor"],
        party=party,
        recent_events=serialize_events(events),
    ), 200


@bp.post("/v1/play/campaigns/<campaign_id>/locations")
@require_auth
def create_play_campaign_location(username, _role, campaign_id):
    data = request.get_json(silent=True) or {}
    location_id = data.get("id")
    name = data.get("name")

    if not isinstance(location_id, str) or not location_id:
        return jsonify(error="invalid id"), 400
    if not valid_nonempty_str(name):
        return jsonify(error="invalid name"), 400

    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner, current_location_id FROM play_campaigns WHERE id = ?",
            (campaign_id,),
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        if campaign["owner"] != username:
            return jsonify(error="forbidden"), 403

        existing = conn.execute(
            "SELECT id FROM play_locations WHERE campaign_id = ? AND id = ?",
            (campaign_id, location_id),
        ).fetchone()
        if existing is not None:
            return jsonify(error="location already exists"), 409

        conn.execute(
            "INSERT INTO play_locations (campaign_id, id, name) VALUES (?, ?, ?)",
            (campaign_id, location_id, name),
        )

        if campaign["current_location_id"] is None:
            conn.execute(
                "UPDATE play_campaigns SET current_location_id = ? WHERE id = ?",
                (location_id, campaign_id),
            )

        conn.commit()
    finally:
        conn.close()

    return jsonify(id=location_id, name=name), 201


@bp.post("/v1/play/campaigns/<campaign_id>/locations/<from_id>/connections")
@require_auth
def create_play_campaign_connection(username, _role, campaign_id, from_id):
    data = request.get_json(silent=True) or {}
    to_id = data.get("to_id")
    travel_turns = data.get("travel_turns")

    if not isinstance(to_id, str) or not to_id:
        return jsonify(error="invalid to_id"), 400
    if not valid_int(travel_turns):
        return jsonify(error="invalid travel_turns"), 400

    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        if campaign["owner"] != username:
            return jsonify(error="forbidden"), 403

        from_location = conn.execute(
            "SELECT id FROM play_locations WHERE campaign_id = ? AND id = ?",
            (campaign_id, from_id),
        ).fetchone()
        to_location = conn.execute(
            "SELECT id FROM play_locations WHERE campaign_id = ? AND id = ?",
            (campaign_id, to_id),
        ).fetchone()
        if from_location is None or to_location is None:
            return jsonify(error="location not found"), 400

        existing = conn.execute(
            "SELECT 1 FROM play_connections WHERE campaign_id = ? AND from_id = ? AND to_id = ?",
            (campaign_id, from_id, to_id),
        ).fetchone()
        if existing is not None:
            return jsonify(error="connection already exists"), 400

        conn.execute(
            "INSERT INTO play_connections (campaign_id, from_id, to_id, travel_turns) "
            "VALUES (?, ?, ?, ?)",
            (campaign_id, from_id, to_id, travel_turns),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify(from_id=from_id, to_id=to_id, travel_turns=travel_turns), 201


@bp.get("/v1/play/campaigns/<campaign_id>/locations/<loc_id>/travel")
@require_auth
def get_play_campaign_travel(username, _role, campaign_id, loc_id):
    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        is_member = conn.execute(
            "SELECT 1 FROM play_members WHERE campaign_id = ? AND username = ?",
            (campaign_id, username),
        ).fetchone()

        if campaign["owner"] != username and is_member is None:
            return jsonify(error="not a campaign member"), 403

        destinations = conn.execute(
            "SELECT play_connections.to_id AS id, play_locations.name AS name, "
            "play_connections.travel_turns AS travel_turns "
            "FROM play_connections JOIN play_locations "
            "ON play_locations.campaign_id = play_connections.campaign_id "
            "AND play_locations.id = play_connections.to_id "
            "WHERE play_connections.campaign_id = ? AND play_connections.from_id = ? "
            "ORDER BY play_connections.to_id",
            (campaign_id, loc_id),
        ).fetchall()
    finally:
        conn.close()

    return jsonify(
        destinations=[
            {"id": d["id"], "name": d["name"], "travel_turns": d["travel_turns"]}
            for d in destinations
        ]
    ), 200


@bp.post("/v1/play/campaigns/<campaign_id>/turn/travel")
@require_auth
def travel_play_campaign_turn(username, _role, campaign_id):
    data = request.get_json(silent=True) or {}
    destination_id = data.get("destination_id")

    if not isinstance(destination_id, str) or not destination_id:
        return jsonify(error="invalid destination_id"), 400

    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner, current_actor, current_location_id "
            "FROM play_campaigns WHERE id = ?",
            (campaign_id,),
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        member = conn.execute(
            "SELECT username FROM play_members WHERE campaign_id = ? AND username = ?",
            (campaign_id, username),
        ).fetchone()

        if member is None:
            if username == campaign["owner"]:
                return jsonify(error="cannot travel"), 409
            return jsonify(error="not a campaign member"), 403

        if campaign["current_actor"] != username:
            return jsonify(error="cannot travel"), 409

        connection = conn.execute(
            "SELECT travel_turns FROM play_connections "
            "WHERE campaign_id = ? AND from_id = ? AND to_id = ?",
            (campaign_id, campaign["current_location_id"], destination_id),
        ).fetchone()
        if connection is None:
            return jsonify(error="invalid destination"), 409

        sequence = next_sequence(conn, campaign_id)

        conn.execute(
            "INSERT INTO play_events (campaign_id, sequence, kind, actor, text) "
            "VALUES (?, ?, ?, ?, ?)",
            (campaign_id, sequence, "travel", username, destination_id),
        )
        conn.execute(
            "UPDATE play_campaigns SET current_actor = ?, current_location_id = ? "
            "WHERE id = ?",
            ("dm", destination_id, campaign_id),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify(
        sequence=sequence,
        kind="travel",
        actor=username,
        destination_id=destination_id,
        travel_turns=connection["travel_turns"],
        next_actor="dm",
    ), 201


@bp.post("/v1/play/campaigns/<campaign_id>/encounters")
@require_auth
def create_play_campaign_encounter(username, _role, campaign_id):
    data = request.get_json(silent=True) or {}
    encounter_id = data.get("id")
    name = data.get("name")

    if not isinstance(encounter_id, str) or not encounter_id:
        return jsonify(error="invalid id"), 400
    if not valid_nonempty_str(name):
        return jsonify(error="invalid name"), 400

    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        if campaign["owner"] != username:
            return jsonify(error="forbidden"), 403

        existing = conn.execute(
            "SELECT id FROM play_encounters WHERE campaign_id = ? AND id = ?",
            (campaign_id, encounter_id),
        ).fetchone()
        active_encounter = conn.execute(
            "SELECT id FROM play_encounters WHERE campaign_id = ? AND status = 'active'",
            (campaign_id,),
        ).fetchone()
        if existing is not None or active_encounter is not None:
            return jsonify(error="cannot create encounter"), 409

        conn.execute(
            "INSERT INTO play_encounters (campaign_id, id, name, status) VALUES (?, ?, ?, ?)",
            (campaign_id, encounter_id, name, "active"),
        )

        campaign_row = conn.execute(
            "SELECT current_actor, in_combat, pre_combat_actor FROM play_campaigns WHERE id = ?",
            (campaign_id,),
        ).fetchone()
        if not campaign_row["in_combat"]:
            conn.execute(
                "UPDATE play_campaigns SET in_combat = 1, pre_combat_actor = ? WHERE id = ?",
                (campaign_row["current_actor"], campaign_id),
            )
        conn.commit()
    finally:
        conn.close()

    return jsonify(id=encounter_id, name=name, status="active", combatants=[]), 201


@bp.post("/v1/play/campaigns/<campaign_id>/encounters/<enc_id>/monsters")
@require_auth
def create_play_encounter_monster(username, _role, campaign_id, enc_id):
    data = request.get_json(silent=True) or {}
    monster_id = data.get("monster_id")
    name = data.get("name")
    hp_max = data.get("hp_max")
    initiative = data.get("initiative")

    if not isinstance(monster_id, str) or not monster_id:
        return jsonify(error="invalid monster_id"), 400
    if not valid_nonempty_str(name):
        return jsonify(error="invalid name"), 400
    if not valid_int(hp_max) or hp_max <= 0:
        return jsonify(error="invalid hp_max"), 400
    if not valid_int(initiative):
        return jsonify(error="invalid initiative"), 400

    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        if campaign["owner"] != username:
            return jsonify(error="forbidden"), 403

        encounter = conn.execute(
            "SELECT id FROM play_encounters WHERE campaign_id = ? AND id = ?",
            (campaign_id, enc_id),
        ).fetchone()
        if encounter is None:
            return jsonify(error="encounter not found"), 404

        existing = conn.execute(
            "SELECT monster_id FROM play_encounter_monsters "
            "WHERE campaign_id = ? AND encounter_id = ? AND monster_id = ?",
            (campaign_id, enc_id, monster_id),
        ).fetchone()
        if existing is not None:
            return jsonify(error="monster already exists"), 409

        conn.execute(
            "INSERT INTO play_encounter_monsters "
            "(campaign_id, encounter_id, monster_id, name, hp_max, hp_current, initiative) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (campaign_id, enc_id, monster_id, name, hp_max, hp_max, initiative),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify(
        monster_id=monster_id,
        name=name,
        hp_max=hp_max,
        initiative=initiative,
        hp_current=hp_max,
    ), 201


@bp.delete("/v1/play/campaigns/<campaign_id>/encounters/<enc_id>/monsters/<monster_id>")
@require_auth
def remove_play_encounter_monster(username, _role, campaign_id, enc_id, monster_id):
    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        if campaign["owner"] != username:
            return jsonify(error="forbidden"), 403

        encounter = conn.execute(
            "SELECT id FROM play_encounters WHERE campaign_id = ? AND id = ?",
            (campaign_id, enc_id),
        ).fetchone()
        if encounter is None:
            return jsonify(error="encounter not found"), 404

        monster = conn.execute(
            "SELECT monster_id FROM play_encounter_monsters "
            "WHERE campaign_id = ? AND encounter_id = ? AND monster_id = ?",
            (campaign_id, enc_id, monster_id),
        ).fetchone()
        if monster is None:
            return jsonify(error="monster not found"), 404

        conn.execute(
            "DELETE FROM play_encounter_monsters "
            "WHERE campaign_id = ? AND encounter_id = ? AND monster_id = ?",
            (campaign_id, enc_id, monster_id),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify(removed=monster_id), 200


@bp.post("/v1/play/campaigns/<campaign_id>/encounters/<enc_id>/combatants")
@require_auth
def create_play_encounter_combatant(username, _role, campaign_id, enc_id):
    data = request.get_json(silent=True) or {}
    member = data.get("member")
    initiative = data.get("initiative")

    if not isinstance(member, str) or not member:
        return jsonify(error="invalid member"), 400
    if not valid_int(initiative):
        return jsonify(error="invalid initiative"), 400

    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        if campaign["owner"] != username:
            return jsonify(error="forbidden"), 403

        encounter = conn.execute(
            "SELECT id FROM play_encounters WHERE campaign_id = ? AND id = ?",
            (campaign_id, enc_id),
        ).fetchone()
        if encounter is None:
            return jsonify(error="encounter not found"), 404

        party_member = conn.execute(
            "SELECT character_id, name FROM play_members "
            "WHERE campaign_id = ? AND username = ?",
            (campaign_id, member),
        ).fetchone()
        if party_member is None:
            return jsonify(error="member not found"), 400

        existing = conn.execute(
            "SELECT member FROM play_encounter_combatants "
            "WHERE campaign_id = ? AND encounter_id = ? AND member = ?",
            (campaign_id, enc_id, member),
        ).fetchone()
        if existing is not None:
            return jsonify(error="combatant already exists"), 409

        conn.execute(
            "INSERT INTO play_encounter_combatants "
            "(campaign_id, encounter_id, member, character_id, name, initiative) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (campaign_id, enc_id, member, party_member["character_id"], party_member["name"], initiative),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify(
        member=member,
        character_id=party_member["character_id"],
        name=party_member["name"],
        initiative=initiative,
    ), 201


@bp.delete("/v1/play/campaigns/<campaign_id>/encounters/<enc_id>/combatants/<member>")
@require_auth
def remove_play_encounter_combatant(username, _role, campaign_id, enc_id, member):
    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        if campaign["owner"] != username:
            return jsonify(error="forbidden"), 403

        encounter = conn.execute(
            "SELECT id FROM play_encounters WHERE campaign_id = ? AND id = ?",
            (campaign_id, enc_id),
        ).fetchone()
        if encounter is None:
            return jsonify(error="encounter not found"), 404

        combatant = conn.execute(
            "SELECT member FROM play_encounter_combatants "
            "WHERE campaign_id = ? AND encounter_id = ? AND member = ?",
            (campaign_id, enc_id, member),
        ).fetchone()
        if combatant is None:
            return jsonify(error="combatant not found"), 404

        conn.execute(
            "DELETE FROM play_encounter_combatants "
            "WHERE campaign_id = ? AND encounter_id = ? AND member = ?",
            (campaign_id, enc_id, member),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify(removed=member), 200


def _encounter_initiative_order(conn, campaign_id, enc_id):
    """Deterministic initiative order: highest initiative first, name breaks ties."""
    monsters = conn.execute(
        "SELECT monster_id, name, initiative FROM play_encounter_monsters "
        "WHERE campaign_id = ? AND encounter_id = ?",
        (campaign_id, enc_id),
    ).fetchall()
    combatants = conn.execute(
        "SELECT member, name, initiative FROM play_encounter_combatants "
        "WHERE campaign_id = ? AND encounter_id = ?",
        (campaign_id, enc_id),
    ).fetchall()

    order = [
        {
            "name": row["name"],
            "kind": "monster",
            "initiative": row["initiative"],
            "actor": None,
            "key": row["monster_id"],
        }
        for row in monsters
    ] + [
        {
            "name": row["name"],
            "kind": "player",
            "initiative": row["initiative"],
            "actor": row["member"],
            "key": row["member"],
        }
        for row in combatants
    ]
    order.sort(key=lambda c: (-c["initiative"], c["name"], c["kind"]))

    override = conn.execute(
        "SELECT order_json FROM play_encounter_turn_order "
        "WHERE campaign_id = ? AND encounter_id = ?",
        (campaign_id, enc_id),
    ).fetchone()
    if override is not None:
        by_key = {c["key"]: c for c in order}
        keys = json.loads(override["order_json"])
        reordered = [by_key[k] for k in keys if k in by_key]
        reordered += [c for c in order if c["key"] not in set(keys)]
        order = reordered

    return order


def _save_encounter_turn_order(conn, campaign_id, enc_id, order):
    keys = [c["key"] for c in order]
    conn.execute(
        "INSERT INTO play_encounter_turn_order (campaign_id, encounter_id, order_json) "
        "VALUES (?, ?, ?) "
        "ON CONFLICT(campaign_id, encounter_id) DO UPDATE SET order_json = excluded.order_json",
        (campaign_id, enc_id, json.dumps(keys)),
    )


@bp.get("/v1/play/campaigns/<campaign_id>/encounters/<enc_id>/turn")
@require_auth
def get_play_encounter_turn(username, _role, campaign_id, enc_id):
    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        is_member = conn.execute(
            "SELECT 1 FROM play_members WHERE campaign_id = ? AND username = ?",
            (campaign_id, username),
        ).fetchone()
        if campaign["owner"] != username and is_member is None:
            return jsonify(error="not a campaign member"), 403

        encounter = conn.execute(
            "SELECT id, round, turn_index FROM play_encounters "
            "WHERE campaign_id = ? AND id = ?",
            (campaign_id, enc_id),
        ).fetchone()
        if encounter is None:
            return jsonify(error="encounter not found"), 404

        order = _encounter_initiative_order(conn, campaign_id, enc_id)
    finally:
        conn.close()

    if not order:
        return jsonify(error="no combatants"), 409

    turn_index = encounter["turn_index"] % len(order)
    active = order[turn_index]

    return jsonify(
        round=encounter["round"],
        turn_index=turn_index,
        active={
            "name": active["name"],
            "kind": active["kind"],
            "initiative": active["initiative"],
        },
    ), 200


def _load_encounter_conditions(conn, campaign_id, enc_id):
    """Return {target: [{"condition": ..., "remaining_rounds": ...}, ...]}."""
    rows = conn.execute(
        "SELECT target, condition, remaining_rounds FROM play_encounter_conditions "
        "WHERE campaign_id = ? AND encounter_id = ? ORDER BY id",
        (campaign_id, enc_id),
    ).fetchall()
    conditions = {}
    for row in rows:
        conditions.setdefault(row["target"], []).append(
            {"condition": row["condition"], "remaining_rounds": row["remaining_rounds"]}
        )
    return conditions


@bp.post("/v1/play/campaigns/<campaign_id>/encounters/<enc_id>/conditions")
@require_auth
def add_play_encounter_condition(username, _role, campaign_id, enc_id):
    data = request.get_json(silent=True) or {}
    target = data.get("target")
    condition = data.get("condition")
    duration_rounds = data.get("duration_rounds")

    if not isinstance(target, str) or not target:
        return jsonify(error="invalid target"), 400
    if not isinstance(condition, str) or not condition:
        return jsonify(error="invalid condition"), 400
    if not valid_int(duration_rounds) or duration_rounds <= 0:
        return jsonify(error="invalid duration_rounds"), 400

    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        if campaign["owner"] != username:
            return jsonify(error="forbidden"), 403

        encounter = conn.execute(
            "SELECT id FROM play_encounters WHERE campaign_id = ? AND id = ?",
            (campaign_id, enc_id),
        ).fetchone()
        if encounter is None:
            return jsonify(error="encounter not found"), 404

        order = _encounter_initiative_order(conn, campaign_id, enc_id)
        if target not in {c["key"] for c in order}:
            return jsonify(error="invalid target"), 400

        conn.execute(
            "INSERT INTO play_encounter_conditions "
            "(campaign_id, encounter_id, target, condition, remaining_rounds) "
            "VALUES (?, ?, ?, ?, ?)",
            (campaign_id, enc_id, target, condition, duration_rounds),
        )
        conn.commit()

        conditions = _load_encounter_conditions(conn, campaign_id, enc_id).get(target, [])
    finally:
        conn.close()

    return jsonify(target=target, conditions=conditions), 201


@bp.get("/v1/play/campaigns/<campaign_id>/encounters/<enc_id>/status")
@require_auth
def get_play_encounter_status(username, _role, campaign_id, enc_id):
    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        is_member = conn.execute(
            "SELECT 1 FROM play_members WHERE campaign_id = ? AND username = ?",
            (campaign_id, username),
        ).fetchone()
        if campaign["owner"] != username and is_member is None:
            return jsonify(error="not a campaign member"), 403

        encounter = conn.execute(
            "SELECT id, round, turn_index FROM play_encounters "
            "WHERE campaign_id = ? AND id = ?",
            (campaign_id, enc_id),
        ).fetchone()
        if encounter is None:
            return jsonify(error="encounter not found"), 404

        order = _encounter_initiative_order(conn, campaign_id, enc_id)
        conditions = _load_encounter_conditions(conn, campaign_id, enc_id)
    finally:
        conn.close()

    if not order:
        return jsonify(error="no combatants"), 409

    turn_index = encounter["turn_index"] % len(order)
    active = order[turn_index]

    return jsonify(
        round=encounter["round"],
        turn_index=turn_index,
        active={
            "name": active["name"],
            "kind": active["kind"],
            "initiative": active["initiative"],
        },
        order=[
            {"name": c["name"], "kind": c["kind"], "initiative": c["initiative"]}
            for c in order
        ],
        conditions=conditions,
    ), 200


@bp.post("/v1/play/campaigns/<campaign_id>/encounters/<enc_id>/turn/advance")
@require_auth
def advance_play_encounter_turn(username, _role, campaign_id, enc_id):
    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        is_member = conn.execute(
            "SELECT 1 FROM play_members WHERE campaign_id = ? AND username = ?",
            (campaign_id, username),
        ).fetchone()
        if campaign["owner"] != username and is_member is None:
            return jsonify(error="not a campaign member"), 403

        encounter = conn.execute(
            "SELECT id, round, turn_index FROM play_encounters "
            "WHERE campaign_id = ? AND id = ?",
            (campaign_id, enc_id),
        ).fetchone()
        if encounter is None:
            return jsonify(error="encounter not found"), 404

        order = _encounter_initiative_order(conn, campaign_id, enc_id)
        if not order:
            return jsonify(error="no combatants"), 409

        current_index = encounter["turn_index"] % len(order)
        active = order[current_index]

        if campaign["owner"] != username and active["actor"] != username:
            return jsonify(error="not your turn"), 409

        next_index = current_index + 1
        if next_index >= len(order):
            next_index = 0
            round_number = encounter["round"] + 1
        else:
            round_number = encounter["round"]

        conn.execute(
            "UPDATE play_encounters SET round = ?, turn_index = ? "
            "WHERE campaign_id = ? AND id = ?",
            (round_number, next_index, campaign_id, enc_id),
        )

        new_active = order[next_index]
        conn.execute(
            "UPDATE play_encounter_conditions SET remaining_rounds = remaining_rounds - 1 "
            "WHERE campaign_id = ? AND encounter_id = ? AND target = ?",
            (campaign_id, enc_id, new_active["key"]),
        )
        conn.execute(
            "DELETE FROM play_encounter_conditions "
            "WHERE campaign_id = ? AND encounter_id = ? AND target = ? AND remaining_rounds <= 0",
            (campaign_id, enc_id, new_active["key"]),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify(
        round=round_number,
        turn_index=next_index,
        active={
            "name": new_active["name"],
            "kind": new_active["kind"],
            "initiative": new_active["initiative"],
        },
    ), 200


@bp.post("/v1/play/campaigns/<campaign_id>/encounters/<enc_id>/turn/delay")
@require_auth
def delay_play_encounter_turn(username, _role, campaign_id, enc_id):
    data = request.get_json(silent=True) or {}
    index = data.get("new_index")

    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        is_member = conn.execute(
            "SELECT 1 FROM play_members WHERE campaign_id = ? AND username = ?",
            (campaign_id, username),
        ).fetchone()
        if campaign["owner"] != username and is_member is None:
            return jsonify(error="not a campaign member"), 403

        encounter = conn.execute(
            "SELECT id, round, turn_index FROM play_encounters "
            "WHERE campaign_id = ? AND id = ?",
            (campaign_id, enc_id),
        ).fetchone()
        if encounter is None:
            return jsonify(error="encounter not found"), 404

        order = _encounter_initiative_order(conn, campaign_id, enc_id)
        if not order:
            return jsonify(error="no combatants"), 409

        current_index = encounter["turn_index"] % len(order)
        active = order[current_index]

        if campaign["owner"] != username and active["actor"] != username:
            return jsonify(error="not your turn"), 409

        if not valid_int(index) or index <= current_index or index >= len(order):
            return jsonify(error="invalid index"), 400

        remainder = order[:current_index] + order[current_index + 1:]
        new_order = remainder[:index] + [active] + remainder[index:]

        _save_encounter_turn_order(conn, campaign_id, enc_id, new_order)
        conn.execute(
            "UPDATE play_encounters SET turn_index = ? WHERE campaign_id = ? AND id = ?",
            (index, campaign_id, enc_id),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify(
        order=[
            {"name": c["name"], "kind": c["kind"], "initiative": c["initiative"]}
            for c in new_order
        ],
    ), 200


@bp.post("/v1/play/campaigns/<campaign_id>/encounters/<enc_id>/turn/ready")
@require_auth
def ready_play_encounter_turn(username, _role, campaign_id, enc_id):
    data = request.get_json(silent=True) or {}
    trigger = data.get("trigger")

    if not valid_nonempty_str(trigger):
        return jsonify(error="invalid trigger"), 400

    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        is_member = conn.execute(
            "SELECT 1 FROM play_members WHERE campaign_id = ? AND username = ?",
            (campaign_id, username),
        ).fetchone()
        if campaign["owner"] != username and is_member is None:
            return jsonify(error="not a campaign member"), 403

        encounter = conn.execute(
            "SELECT id, round, turn_index FROM play_encounters "
            "WHERE campaign_id = ? AND id = ?",
            (campaign_id, enc_id),
        ).fetchone()
        if encounter is None:
            return jsonify(error="encounter not found"), 404

        order = _encounter_initiative_order(conn, campaign_id, enc_id)
        if not order:
            return jsonify(error="no combatants"), 409

        current_index = encounter["turn_index"] % len(order)
        active = order[current_index]

        if active["actor"] != username:
            return jsonify(error="not your turn"), 409

        sequence = next_sequence(conn, campaign_id)
        conn.execute(
            "INSERT INTO play_events (campaign_id, sequence, kind, actor, type, target, text) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (campaign_id, sequence, "ready_action", username, "ready", None, trigger),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify(actor=active["actor"], trigger=trigger), 201


VALID_COMBAT_ACTION_TYPES = ("attack", "help", "dodge", "ready")


@bp.post("/v1/play/campaigns/<campaign_id>/encounters/<enc_id>/actions")
@require_auth
def submit_play_encounter_action(username, _role, campaign_id, enc_id):
    data = request.get_json(silent=True) or {}
    action_type = data.get("type")
    target = data.get("target")
    text = data.get("text")

    if action_type not in VALID_COMBAT_ACTION_TYPES:
        return jsonify(error="invalid type"), 400
    if not valid_nonempty_str(text):
        return jsonify(error="invalid text"), 400
    if target is not None and not isinstance(target, str):
        return jsonify(error="invalid target"), 400

    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        is_member = conn.execute(
            "SELECT 1 FROM play_members WHERE campaign_id = ? AND username = ?",
            (campaign_id, username),
        ).fetchone()
        if campaign["owner"] != username and is_member is None:
            return jsonify(error="not a campaign member"), 403

        encounter = conn.execute(
            "SELECT id, round, turn_index FROM play_encounters "
            "WHERE campaign_id = ? AND id = ?",
            (campaign_id, enc_id),
        ).fetchone()
        if encounter is None:
            return jsonify(error="encounter not found"), 404

        order = _encounter_initiative_order(conn, campaign_id, enc_id)
        if not order:
            return jsonify(error="no combatants"), 409

        current_index = encounter["turn_index"] % len(order)
        active = order[current_index]

        if active["actor"] != username:
            return jsonify(error="not your turn"), 409

        sequence = next_sequence(conn, campaign_id)

        conn.execute(
            "INSERT INTO play_events (campaign_id, sequence, kind, actor, type, target, text) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (campaign_id, sequence, "combat_action", username, action_type, target, text),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify(
        sequence=sequence,
        kind="combat_action",
        actor=username,
        type=action_type,
        target=target,
        text=text,
    ), 201


def _find_encounter_target(conn, campaign_id, enc_id, target):
    monster = conn.execute(
        "SELECT monster_id AS key, hp_current, hp_max FROM play_encounter_monsters "
        "WHERE campaign_id = ? AND encounter_id = ? AND monster_id = ?",
        (campaign_id, enc_id, target),
    ).fetchone()
    if monster is not None:
        return "monster", monster

    combatant = conn.execute(
        "SELECT play_encounter_combatants.member AS key, "
        "play_members.hp_current AS hp_current, play_members.hp_max AS hp_max "
        "FROM play_encounter_combatants "
        "JOIN play_members "
        "ON play_members.campaign_id = play_encounter_combatants.campaign_id "
        "AND play_members.username = play_encounter_combatants.member "
        "WHERE play_encounter_combatants.campaign_id = ? "
        "AND play_encounter_combatants.encounter_id = ? "
        "AND play_encounter_combatants.member = ?",
        (campaign_id, enc_id, target),
    ).fetchone()
    if combatant is not None:
        return "player", combatant

    return None, None


@bp.post("/v1/play/campaigns/<campaign_id>/encounters/<enc_id>/damage")
@require_auth
def damage_play_encounter_target(username, _role, campaign_id, enc_id):
    data = request.get_json(silent=True) or {}
    target = data.get("target")
    amount = data.get("amount")

    if not isinstance(target, str) or not target:
        return jsonify(error="invalid target"), 400
    if not valid_int(amount) or amount < 0:
        return jsonify(error="invalid amount"), 400

    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        if campaign["owner"] != username:
            return jsonify(error="forbidden"), 403

        encounter = conn.execute(
            "SELECT id FROM play_encounters WHERE campaign_id = ? AND id = ?",
            (campaign_id, enc_id),
        ).fetchone()
        if encounter is None:
            return jsonify(error="encounter not found"), 404

        kind, row = _find_encounter_target(conn, campaign_id, enc_id, target)
        if row is None:
            return jsonify(error="target not found"), 404

        hp_before = row["hp_current"]
        hp_after = max(0, hp_before - amount)

        if kind == "monster":
            conn.execute(
                "UPDATE play_encounter_monsters SET hp_current = ? "
                "WHERE campaign_id = ? AND encounter_id = ? AND monster_id = ?",
                (hp_after, campaign_id, enc_id, target),
            )
        else:
            conn.execute(
                "UPDATE play_members SET hp_current = ? "
                "WHERE campaign_id = ? AND username = ?",
                (hp_after, campaign_id, target),
            )
        conn.commit()
    finally:
        conn.close()

    return jsonify(
        target=target,
        hp_before=hp_before,
        hp_after=hp_after,
        damage=amount,
    ), 200


@bp.post("/v1/play/campaigns/<campaign_id>/encounters/<enc_id>/heal")
@require_auth
def heal_play_encounter_target(username, _role, campaign_id, enc_id):
    data = request.get_json(silent=True) or {}
    target = data.get("target")
    amount = data.get("amount")

    if not isinstance(target, str) or not target:
        return jsonify(error="invalid target"), 400
    if not valid_int(amount) or amount < 0:
        return jsonify(error="invalid amount"), 400

    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        if campaign["owner"] != username:
            return jsonify(error="forbidden"), 403

        encounter = conn.execute(
            "SELECT id FROM play_encounters WHERE campaign_id = ? AND id = ?",
            (campaign_id, enc_id),
        ).fetchone()
        if encounter is None:
            return jsonify(error="encounter not found"), 404

        kind, row = _find_encounter_target(conn, campaign_id, enc_id, target)
        if row is None:
            return jsonify(error="target not found"), 404

        hp_before = row["hp_current"]
        hp_after = min(row["hp_max"], hp_before + amount)

        if kind == "monster":
            conn.execute(
                "UPDATE play_encounter_monsters SET hp_current = ? "
                "WHERE campaign_id = ? AND encounter_id = ? AND monster_id = ?",
                (hp_after, campaign_id, enc_id, target),
            )
        else:
            conn.execute(
                "UPDATE play_members SET hp_current = ? "
                "WHERE campaign_id = ? AND username = ?",
                (hp_after, campaign_id, target),
            )
        conn.commit()
    finally:
        conn.close()

    return jsonify(
        target=target,
        hp_before=hp_before,
        hp_after=hp_after,
        healing=amount,
    ), 200


def _find_member_by_character(conn, campaign_id, char_id):
    return conn.execute(
        "SELECT username, hp_current, hp_max, status, "
        "death_save_successes, death_save_failures "
        "FROM play_members WHERE campaign_id = ? AND character_id = ?",
        (campaign_id, char_id),
    ).fetchone()


@bp.post("/v1/play/campaigns/<campaign_id>/characters/<char_id>/damage")
@require_auth
def damage_play_campaign_character(username, _role, campaign_id, char_id):
    data = request.get_json(silent=True) or {}
    amount = data.get("amount")

    if not valid_int(amount) or amount < 0:
        return jsonify(error="invalid amount"), 400

    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        if campaign["owner"] != username:
            return jsonify(error="forbidden"), 403

        member = _find_member_by_character(conn, campaign_id, char_id)
        if member is None:
            return jsonify(error="character not found"), 404

        hp_before = member["hp_current"]
        hp_after = max(0, hp_before - amount)
        status = "unconscious" if hp_after == 0 else member["status"]
        successes = member["death_save_successes"]
        failures = member["death_save_failures"]
        if hp_after == 0 and member["status"] != "unconscious":
            successes = 0
            failures = 0

        conn.execute(
            "UPDATE play_members SET hp_current = ?, status = ?, "
            "death_save_successes = ?, death_save_failures = ? "
            "WHERE campaign_id = ? AND character_id = ?",
            (hp_after, status, successes, failures, campaign_id, char_id),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify(
        character_id=char_id,
        target=char_id,
        hp_before=hp_before,
        hp_after=hp_after,
        hp_current=hp_after,
        hp_max=member["hp_max"],
        damage=amount,
        status=status,
    ), 200


@bp.post("/v1/play/campaigns/<campaign_id>/characters/<char_id>/death-saves")
@require_auth
def death_save_play_campaign_character(username, _role, campaign_id, char_id):
    data = request.get_json(silent=True) or {}
    outcome = data.get("outcome")

    if outcome not in ("success", "failure"):
        return jsonify(error="invalid outcome"), 400

    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        member = _find_member_by_character(conn, campaign_id, char_id)
        if member is None:
            return jsonify(error="character not found"), 404

        if member["username"] != username:
            return jsonify(error="forbidden"), 403

        if member["status"] != "unconscious":
            return jsonify(error="cannot roll death save"), 409

        successes = member["death_save_successes"]
        failures = member["death_save_failures"]

        if outcome == "success":
            successes += 1
        else:
            failures += 1

        status = member["status"]
        if successes >= 3:
            status = "stable"
        elif failures >= 3:
            status = "dead"

        conn.execute(
            "UPDATE play_members SET death_save_successes = ?, "
            "death_save_failures = ?, status = ? "
            "WHERE campaign_id = ? AND character_id = ?",
            (successes, failures, status, campaign_id, char_id),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify(
        character_id=char_id,
        successes=successes,
        failures=failures,
        status=status,
    ), 201


@bp.get("/v1/play/campaigns/<campaign_id>/characters/<char_id>/status")
@require_auth
def get_play_campaign_character_status(username, _role, campaign_id, char_id):
    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        is_member = conn.execute(
            "SELECT 1 FROM play_members WHERE campaign_id = ? AND username = ?",
            (campaign_id, username),
        ).fetchone()
        if campaign["owner"] != username and is_member is None:
            return jsonify(error="not a campaign member"), 403

        member = _find_member_by_character(conn, campaign_id, char_id)
        if member is None:
            return jsonify(error="character not found"), 404
    finally:
        conn.close()

    return jsonify(
        character_id=char_id,
        hp_current=member["hp_current"],
        hp_max=member["hp_max"],
        status=member["status"],
    ), 200


def _require_campaign_member(conn, campaign, username):
    """None when the requester is the campaign owner or a play_members row;
    otherwise the (body, status) tuple to return."""
    is_member = conn.execute(
        "SELECT 1 FROM play_members WHERE campaign_id = ? AND username = ?",
        (campaign["id"], username),
    ).fetchone()
    if campaign["owner"] != username and is_member is None:
        return jsonify(error="not a campaign member"), 403
    return None


@bp.get("/v1/play/campaigns/<campaign_id>/characters/<char_id>/owner")
@require_auth
def get_play_campaign_character_owner(username, _role, campaign_id, char_id):
    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        membership_error = _require_campaign_member(conn, campaign, username)
        if membership_error is not None:
            return membership_error

        record = conn.execute(
            "SELECT owner FROM play_character_owners "
            "WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, char_id),
        ).fetchone()
        if record is None:
            return jsonify(error="character not found"), 404
    finally:
        conn.close()

    return jsonify(character_id=char_id, owner=record["owner"]), 200


@bp.post("/v1/play/campaigns/<campaign_id>/characters/<char_id>/claim")
@require_auth
def claim_play_campaign_character(username, role, campaign_id, char_id):
    if role != "player":
        return jsonify(error="forbidden"), 403

    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        membership_error = _require_campaign_member(conn, campaign, username)
        if membership_error is not None:
            return membership_error

        record = conn.execute(
            "SELECT owner FROM play_character_owners "
            "WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, char_id),
        ).fetchone()

        if record is not None and record["owner"] is not None and record["owner"] != username:
            return jsonify(error="character already owned"), 409

        if record is None:
            conn.execute(
                "INSERT INTO play_character_owners (campaign_id, character_id, owner) "
                "VALUES (?, ?, ?)",
                (campaign_id, char_id, username),
            )
        else:
            conn.execute(
                "UPDATE play_character_owners SET owner = ? "
                "WHERE campaign_id = ? AND character_id = ?",
                (username, campaign_id, char_id),
            )
        conn.commit()
    finally:
        conn.close()

    return jsonify(character_id=char_id, owner=username), 201


@bp.post("/v1/play/campaigns/<campaign_id>/characters/<char_id>/transfer")
@require_auth
def transfer_play_campaign_character(username, _role, campaign_id, char_id):
    data = request.get_json(silent=True) or {}
    new_owner = data.get("new_owner")

    if not valid_nonempty_str(new_owner):
        return jsonify(error="invalid new_owner"), 400

    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        membership_error = _require_campaign_member(conn, campaign, username)
        if membership_error is not None:
            return membership_error

        record = conn.execute(
            "SELECT owner FROM play_character_owners "
            "WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, char_id),
        ).fetchone()
        if record is None:
            return jsonify(error="character not found"), 404

        if record["owner"] != username:
            return jsonify(error="forbidden"), 403

        new_owner_is_member = conn.execute(
            "SELECT 1 FROM play_members WHERE campaign_id = ? AND username = ?",
            (campaign_id, new_owner),
        ).fetchone()
        if campaign["owner"] != new_owner and new_owner_is_member is None:
            return jsonify(error="invalid new_owner"), 400

        conn.execute(
            "UPDATE play_character_owners SET owner = ? "
            "WHERE campaign_id = ? AND character_id = ?",
            (new_owner, campaign_id, char_id),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify(character_id=char_id, owner=new_owner), 200


@bp.post("/v1/play/campaigns/<campaign_id>/characters/<char_id>/build")
@require_auth
def build_play_campaign_character(username, _role, campaign_id, char_id):
    data = request.get_json(silent=True) or {}
    race = data.get("race")
    char_class = data.get("class")
    background = data.get("background")
    abilities = data.get("abilities")

    if race not in VALID_RACES:
        return jsonify(error="invalid race"), 400
    if char_class not in HIT_DICE:
        return jsonify(error="invalid class"), 400
    if background not in VALID_BACKGROUNDS:
        return jsonify(error="invalid background"), 400
    if not isinstance(abilities, dict):
        return jsonify(error="invalid abilities"), 400
    for key in ABILITY_KEYS:
        score = abilities.get(key)
        if not valid_int(score) or not (1 <= score <= 30):
            return jsonify(error="invalid abilities"), 400

    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        record = conn.execute(
            "SELECT owner FROM play_character_owners "
            "WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, char_id),
        ).fetchone()
        if record is None:
            return jsonify(error="character not found"), 404

        if record["owner"] != username:
            return jsonify(error="forbidden"), 403

        level = 1
        modifiers = {key: ability_modifier(abilities[key]) for key in ABILITY_KEYS}
        con_modifier = modifiers["con"]
        hp_max = hp_max_at_level1(char_class, con_modifier)
        prof_bonus = proficiency_bonus(level)

        conn.execute(
            "UPDATE play_character_owners SET race = ?, class = ?, background = ?, "
            "level = ?, hp_max = ?, proficiency_bonus = ?, con_modifier = ?, "
            "str_modifier = ?, dex_modifier = ?, int_modifier = ?, wis_modifier = ?, "
            "cha_modifier = ? WHERE campaign_id = ? AND character_id = ?",
            (
                race,
                char_class,
                background,
                level,
                hp_max,
                prof_bonus,
                con_modifier,
                modifiers["str"],
                modifiers["dex"],
                modifiers["int"],
                modifiers["wis"],
                modifiers["cha"],
                campaign_id,
                char_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify(
        character_id=char_id,
        race=race,
        background=background,
        level=level,
        hp_max=hp_max,
        proficiency_bonus=prof_bonus,
        **{"class": char_class},
    ), 200


@bp.post("/v1/play/campaigns/<campaign_id>/characters/<char_id>/level-up")
@require_auth
def level_up_play_campaign_character(username, _role, campaign_id, char_id):
    data = request.get_json(silent=True) or {}
    new_level = data.get("level")

    if not valid_int(new_level):
        return jsonify(error="invalid level"), 400

    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        record = conn.execute(
            "SELECT owner, class, level, hp_max, con_modifier FROM play_character_owners "
            "WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, char_id),
        ).fetchone()
        if record is None:
            return jsonify(error="character not found"), 404

        if record["owner"] != username:
            return jsonify(error="forbidden"), 403

        current_level = record["level"]
        if current_level is None or new_level != current_level + 1:
            return jsonify(error="invalid level"), 400

        char_class = record["class"]
        con_modifier = record["con_modifier"] or 0
        hit_die = HIT_DICE[char_class]
        hp_max = record["hp_max"] + average_hit_die_value(hit_die) + con_modifier
        prof_bonus = proficiency_bonus(new_level)
        hit_dice = f"1d{hit_die}"

        conn.execute(
            "UPDATE play_character_owners SET level = ?, hp_max = ?, "
            "proficiency_bonus = ? WHERE campaign_id = ? AND character_id = ?",
            (new_level, hp_max, prof_bonus, campaign_id, char_id),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify(
        character_id=char_id,
        level=new_level,
        hp_max=hp_max,
        hit_dice=hit_dice,
        proficiency_bonus=prof_bonus,
    ), 200


@bp.post("/v1/play/campaigns/<campaign_id>/characters/<char_id>/skill-check")
@require_auth
def skill_check_play_campaign_character(username, _role, campaign_id, char_id):
    data = request.get_json(silent=True) or {}
    skill = data.get("skill")
    ability = data.get("ability")
    proficient = bool(data.get("proficient"))
    roll = data.get("roll")

    if skill not in VALID_SKILLS:
        return jsonify(error="invalid skill"), 400
    if ability not in ABILITY_KEYS:
        return jsonify(error="invalid ability"), 400
    if not valid_int(roll):
        return jsonify(error="invalid roll"), 400

    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        record = conn.execute(
            "SELECT owner, proficiency_bonus, str_modifier, dex_modifier, "
            "con_modifier, int_modifier, wis_modifier, cha_modifier "
            "FROM play_character_owners WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, char_id),
        ).fetchone()
        if record is None:
            return jsonify(error="character not found"), 404

        if record["owner"] != username:
            return jsonify(error="forbidden"), 403

        ability_mod = record[MODIFIER_COLUMNS[ability]] or 0
        prof_bonus = record["proficiency_bonus"] or 0
        modifier = ability_mod + (prof_bonus if proficient else 0)
        total = roll + modifier
    finally:
        conn.close()

    return jsonify(
        character_id=char_id,
        skill=skill,
        ability=ability,
        modifier=modifier,
        total=total,
    ), 200


@bp.post("/v1/play/campaigns/<campaign_id>/turn/rest")
@require_auth
def rest_play_campaign_turn(username, _role, campaign_id):
    data = request.get_json(silent=True) or {}
    rest_type = data.get("type")

    if rest_type not in ("short", "long"):
        return jsonify(error="invalid type"), 400

    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner, current_actor FROM play_campaigns WHERE id = ?",
            (campaign_id,),
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        member = conn.execute(
            "SELECT username, hp_current, hp_max FROM play_members "
            "WHERE campaign_id = ? AND username = ?",
            (campaign_id, username),
        ).fetchone()

        if member is None:
            if username == campaign["owner"]:
                return jsonify(error="cannot rest"), 409
            return jsonify(error="not a campaign member"), 403

        if campaign["current_actor"] != username:
            return jsonify(error="cannot rest"), 409

        hp_current = member["hp_max"] if rest_type == "long" else member["hp_current"]

        if rest_type == "long":
            conn.execute(
                "UPDATE play_members SET hp_current = ? WHERE campaign_id = ? AND username = ?",
                (hp_current, campaign_id, username),
            )

        sequence = next_sequence(conn, campaign_id)

        conn.execute(
            "INSERT INTO play_events (campaign_id, sequence, kind, actor, type, text) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (campaign_id, sequence, "rest", username, rest_type, rest_type),
        )
        conn.execute(
            "UPDATE play_campaigns SET current_actor = ? WHERE id = ?",
            ("dm", campaign_id),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify(
        sequence=sequence,
        kind="rest",
        actor=username,
        type=rest_type,
        hp_current=hp_current,
        hp_max=member["hp_max"],
        next_actor="dm",
    ), 201


def _valid_loot(loot):
    if not isinstance(loot, list):
        return False
    for item in loot:
        if not isinstance(item, dict):
            return False
        if not valid_slug(item.get("slug")):
            return False
        if not valid_int(item.get("quantity")) or item.get("quantity") <= 0:
            return False
    return True


@bp.post("/v1/play/campaigns/<campaign_id>/encounters/<enc_id>/rewards")
@require_auth
def award_play_encounter_rewards(username, _role, campaign_id, enc_id):
    data = request.get_json(silent=True) or {}
    xp = data.get("xp")
    loot = data.get("loot", [])

    if not valid_int(xp) or xp < 0:
        return jsonify(error="invalid xp"), 400
    if not _valid_loot(loot):
        return jsonify(error="invalid loot"), 400

    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        if campaign["owner"] != username:
            return jsonify(error="forbidden"), 403

        encounter = conn.execute(
            "SELECT id FROM play_encounters WHERE campaign_id = ? AND id = ?",
            (campaign_id, enc_id),
        ).fetchone()
        if encounter is None:
            return jsonify(error="encounter not found"), 404

        existing = conn.execute(
            "SELECT campaign_id FROM play_encounter_rewards "
            "WHERE campaign_id = ? AND encounter_id = ?",
            (campaign_id, enc_id),
        ).fetchone()
        if existing is not None:
            return jsonify(error="rewards already awarded"), 409

        conn.execute(
            "INSERT INTO play_encounter_rewards (campaign_id, encounter_id, xp, loot_json) "
            "VALUES (?, ?, ?, ?)",
            (campaign_id, enc_id, xp, json.dumps(loot)),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify(id=enc_id, xp=xp, loot=loot), 200


@bp.post("/v1/play/campaigns/<campaign_id>/encounters/<enc_id>/close")
@require_auth
def close_play_campaign_encounter(username, _role, campaign_id, enc_id):
    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        if campaign["owner"] != username:
            return jsonify(error="forbidden"), 403

        encounter = conn.execute(
            "SELECT id FROM play_encounters WHERE campaign_id = ? AND id = ?",
            (campaign_id, enc_id),
        ).fetchone()
        if encounter is None:
            return jsonify(error="encounter not found"), 404

        reward = conn.execute(
            "SELECT xp FROM play_encounter_rewards "
            "WHERE campaign_id = ? AND encounter_id = ?",
            (campaign_id, enc_id),
        ).fetchone()
        xp_awarded = reward["xp"] if reward is not None else 0

        conn.execute(
            "UPDATE play_encounters SET status = 'closed' WHERE campaign_id = ? AND id = ?",
            (campaign_id, enc_id),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify(id=enc_id, status="closed", xp_awarded=xp_awarded), 200


@bp.post("/v1/play/campaigns/<campaign_id>/encounters/<enc_id>/end")
@require_auth
def end_play_campaign_encounter(username, _role, campaign_id, enc_id):
    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner, status, in_combat, pre_combat_actor "
            "FROM play_campaigns WHERE id = ?",
            (campaign_id,),
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        if campaign["owner"] != username:
            return jsonify(error="forbidden"), 403

        encounter = conn.execute(
            "SELECT id, status FROM play_encounters WHERE campaign_id = ? AND id = ?",
            (campaign_id, enc_id),
        ).fetchone()
        if encounter is None:
            return jsonify(error="encounter not found"), 404

        if not campaign["in_combat"]:
            return jsonify(error="campaign not in combat"), 409

        if encounter["status"] == "active":
            conn.execute(
                "UPDATE play_encounters SET status = 'closed' WHERE campaign_id = ? AND id = ?",
                (campaign_id, enc_id),
            )

        current_actor = campaign["pre_combat_actor"]
        conn.execute(
            "UPDATE play_campaigns SET in_combat = 0, pre_combat_actor = NULL, "
            "current_actor = ? WHERE id = ?",
            (current_actor, campaign_id),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify(
        campaign_id=campaign_id,
        status=campaign["status"],
        phase="exploration",
        current_actor=current_actor,
    ), 200


@bp.post("/v1/play/campaigns/<campaign_id>/characters/<char_id>/spells")
@require_auth
def add_play_campaign_character_spell(username, _role, campaign_id, char_id):
    data = request.get_json(silent=True) or {}
    spell_id = data.get("spell_id")
    name = data.get("name")
    level = data.get("level")

    if not valid_slug(spell_id):
        return jsonify(error="invalid spell_id"), 400
    if not valid_nonempty_str(name):
        return jsonify(error="invalid name"), 400
    if not valid_int(level) or not (0 <= level <= 9):
        return jsonify(error="invalid level"), 400

    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        record = conn.execute(
            "SELECT owner, class FROM play_character_owners "
            "WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, char_id),
        ).fetchone()
        if record is None:
            return jsonify(error="character not found"), 404

        if record["owner"] != username:
            return jsonify(error="forbidden"), 403

        char_class = record["class"]
        if char_class is None:
            member = conn.execute(
                "SELECT class FROM play_members "
                "WHERE campaign_id = ? AND character_id = ?",
                (campaign_id, char_id),
            ).fetchone()
            char_class = member["class"] if member is not None else None

        if not spell_known_by_class(char_class, spell_id):
            return jsonify(error="invalid class/spell combination"), 400

        existing = conn.execute(
            "SELECT 1 FROM play_character_spells "
            "WHERE campaign_id = ? AND character_id = ? AND spell_id = ?",
            (campaign_id, char_id, spell_id),
        ).fetchone()
        if existing is not None:
            return jsonify(error="spell already known"), 409

        conn.execute(
            "INSERT INTO play_character_spells "
            "(campaign_id, character_id, spell_id, name, level) VALUES (?, ?, ?, ?, ?)",
            (campaign_id, char_id, spell_id, name, level),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify(spell_id=spell_id, name=name, level=level), 201


@bp.get("/v1/play/campaigns/<campaign_id>/characters/<char_id>/spells")
@require_auth
def get_play_campaign_character_spells(username, _role, campaign_id, char_id):
    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        membership_error = _require_campaign_member(conn, campaign, username)
        if membership_error is not None:
            return membership_error

        owner_record = conn.execute(
            "SELECT 1 FROM play_character_owners "
            "WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, char_id),
        ).fetchone()
        if owner_record is None:
            return jsonify(error="character not found"), 404

        rows = conn.execute(
            "SELECT spell_id, name, level FROM play_character_spells "
            "WHERE campaign_id = ? AND character_id = ? ORDER BY spell_id",
            (campaign_id, char_id),
        ).fetchall()
    finally:
        conn.close()

    return jsonify(
        spells=[
            {"spell_id": row["spell_id"], "name": row["name"], "level": row["level"]}
            for row in rows
        ]
    ), 200


def _character_max_prepared(record):
    char_class = record["class"]
    ability_col = PREPARED_SPELL_ABILITY.get(char_class)
    ability_mod = record[ability_col] if ability_col else 0
    return max_prepared_spells(char_class, record["level"], ability_mod)


@bp.put("/v1/play/campaigns/<campaign_id>/characters/<char_id>/prepared-spells")
@require_auth
def set_play_campaign_character_prepared_spells(username, _role, campaign_id, char_id):
    data = request.get_json(silent=True) or {}
    spell_ids = data.get("spell_ids")

    if not isinstance(spell_ids, list) or not all(
        valid_slug(spell_id) for spell_id in spell_ids
    ):
        return jsonify(error="invalid spell_ids"), 400

    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        record = conn.execute(
            "SELECT owner, class, level, int_modifier, wis_modifier, cha_modifier "
            "FROM play_character_owners WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, char_id),
        ).fetchone()
        if record is None:
            return jsonify(error="character not found"), 404

        if record["owner"] != username:
            return jsonify(error="forbidden"), 403

        if record["class"] not in SPELLCASTING_CLASSES:
            return jsonify(error="not a spellcasting class"), 400

        known = {
            row["spell_id"]
            for row in conn.execute(
                "SELECT spell_id FROM play_character_spells "
                "WHERE campaign_id = ? AND character_id = ?",
                (campaign_id, char_id),
            ).fetchall()
        }
        if any(spell_id not in known for spell_id in spell_ids):
            return jsonify(error="unknown spell"), 400

        max_prepared = _character_max_prepared(record)
        if len(spell_ids) > max_prepared:
            return jsonify(error="too many prepared spells"), 400

        conn.execute(
            "INSERT INTO play_character_prepared_spells "
            "(campaign_id, character_id, spell_ids_json) VALUES (?, ?, ?) "
            "ON CONFLICT(campaign_id, character_id) "
            "DO UPDATE SET spell_ids_json = excluded.spell_ids_json",
            (campaign_id, char_id, json.dumps(spell_ids)),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify(
        character_id=char_id,
        prepared_spells=spell_ids,
        max_prepared=max_prepared,
    ), 200


@bp.get("/v1/play/campaigns/<campaign_id>/characters/<char_id>/prepared-spells")
@require_auth
def get_play_campaign_character_prepared_spells(username, _role, campaign_id, char_id):
    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        membership_error = _require_campaign_member(conn, campaign, username)
        if membership_error is not None:
            return membership_error

        record = conn.execute(
            "SELECT class, level, int_modifier, wis_modifier, cha_modifier "
            "FROM play_character_owners WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, char_id),
        ).fetchone()
        if record is None:
            return jsonify(error="character not found"), 404

        row = conn.execute(
            "SELECT spell_ids_json FROM play_character_prepared_spells "
            "WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, char_id),
        ).fetchone()
        prepared_spells = json.loads(row["spell_ids_json"]) if row is not None else []
        max_prepared = _character_max_prepared(record)
    finally:
        conn.close()

    return jsonify(
        character_id=char_id,
        prepared_spells=prepared_spells,
        max_prepared=max_prepared,
    ), 200


@bp.post("/v1/play/campaigns/<campaign_id>/characters/<char_id>/casts")
@require_auth
def cast_play_campaign_character_spell(username, _role, campaign_id, char_id):
    data = request.get_json(silent=True) or {}
    spell_id = data.get("spell_id")
    target = data.get("target")

    if not valid_slug(spell_id):
        return jsonify(error="invalid spell_id"), 400
    if not valid_nonempty_str(target):
        return jsonify(error="invalid target"), 400

    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        record = conn.execute(
            "SELECT owner, class, level FROM play_character_owners "
            "WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, char_id),
        ).fetchone()
        if record is None:
            return jsonify(error="character not found"), 404

        if record["owner"] != username:
            return jsonify(error="forbidden"), 403

        if record["class"] not in SPELLCASTING_CLASSES:
            return jsonify(error="not a spellcasting class"), 400

        spell = conn.execute(
            "SELECT level FROM play_character_spells "
            "WHERE campaign_id = ? AND character_id = ? AND spell_id = ?",
            (campaign_id, char_id, spell_id),
        ).fetchone()

        prepared_row = conn.execute(
            "SELECT spell_ids_json FROM play_character_prepared_spells "
            "WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, char_id),
        ).fetchone()
        prepared = (
            json.loads(prepared_row["spell_ids_json"]) if prepared_row is not None else []
        )
        if spell is None or spell_id not in prepared:
            return jsonify(error="spell not prepared"), 400

        spell_level = spell["level"]
        char_level = record["level"] or 1
        slots_max = spell_slots_at_level(char_level, spell_level)
        casts_at_level = conn.execute(
            "SELECT COUNT(*) AS n FROM play_character_casts "
            "WHERE campaign_id = ? AND character_id = ? AND slot_level = ?",
            (campaign_id, char_id, spell_level),
        ).fetchone()["n"]
        slots_remaining = slots_max - casts_at_level
        if slots_remaining < 1:
            return jsonify(error="no spell slots remaining"), 409
        slots_remaining -= 1

        sequence = (
            conn.execute(
                "SELECT COUNT(*) AS n FROM play_character_casts "
                "WHERE campaign_id = ? AND character_id = ?",
                (campaign_id, char_id),
            ).fetchone()["n"]
            + 1
        )

        conn.execute(
            "INSERT INTO play_character_casts "
            "(campaign_id, character_id, sequence, spell_id, target, slot_level, slots_remaining) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (campaign_id, char_id, sequence, spell_id, target, spell_level, slots_remaining),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify(
        character_id=char_id,
        spell_id=spell_id,
        target=target,
        slot_level=spell_level,
        slots_remaining=slots_remaining,
        sequence=sequence,
    ), 201


@bp.get("/v1/play/campaigns/<campaign_id>/characters/<char_id>/casts")
@require_auth
def get_play_campaign_character_casts(username, _role, campaign_id, char_id):
    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        membership_error = _require_campaign_member(conn, campaign, username)
        if membership_error is not None:
            return membership_error

        owner_record = conn.execute(
            "SELECT 1 FROM play_character_owners "
            "WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, char_id),
        ).fetchone()
        if owner_record is None:
            return jsonify(error="character not found"), 404

        rows = conn.execute(
            "SELECT spell_id, target, slot_level, slots_remaining, sequence "
            "FROM play_character_casts "
            "WHERE campaign_id = ? AND character_id = ? ORDER BY sequence",
            (campaign_id, char_id),
        ).fetchall()
    finally:
        conn.close()

    return jsonify(
        casts=[
            {
                "character_id": char_id,
                "spell_id": row["spell_id"],
                "target": row["target"],
                "slot_level": row["slot_level"],
                "slots_remaining": row["slots_remaining"],
                "sequence": row["sequence"],
            }
            for row in rows
        ]
    ), 200


def _serialize_concentration(row):
    if row is None:
        return None
    return {
        "spell_id": row["spell_id"],
        "target": row["target"],
        "remaining_turns": row["remaining_turns"],
    }


@bp.put("/v1/play/campaigns/<campaign_id>/characters/<char_id>/concentration")
@require_auth
def set_play_campaign_character_concentration(username, _role, campaign_id, char_id):
    data = request.get_json(silent=True) or {}
    spell_id = data.get("spell_id")
    target = data.get("target")
    duration_turns = data.get("duration_turns")

    if not valid_slug(spell_id):
        return jsonify(error="invalid spell_id"), 400
    if not valid_nonempty_str(target):
        return jsonify(error="invalid target"), 400
    if not valid_int(duration_turns) or duration_turns < 1:
        return jsonify(error="invalid duration_turns"), 400

    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        record = conn.execute(
            "SELECT owner, class FROM play_character_owners "
            "WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, char_id),
        ).fetchone()
        if record is None:
            return jsonify(error="character not found"), 404

        if record["owner"] != username:
            return jsonify(error="forbidden"), 403

        if record["class"] not in SPELLCASTING_CLASSES:
            return jsonify(error="not a spellcasting class"), 400

        spell = conn.execute(
            "SELECT 1 FROM play_character_spells "
            "WHERE campaign_id = ? AND character_id = ? AND spell_id = ?",
            (campaign_id, char_id, spell_id),
        ).fetchone()

        prepared_row = conn.execute(
            "SELECT spell_ids_json FROM play_character_prepared_spells "
            "WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, char_id),
        ).fetchone()
        prepared = (
            json.loads(prepared_row["spell_ids_json"]) if prepared_row is not None else []
        )
        if spell is None or spell_id not in prepared:
            return jsonify(error="spell not prepared"), 400

        conn.execute(
            "INSERT INTO play_character_concentration "
            "(campaign_id, character_id, spell_id, target, remaining_turns) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT (campaign_id, character_id) "
            "DO UPDATE SET spell_id = excluded.spell_id, target = excluded.target, "
            "remaining_turns = excluded.remaining_turns",
            (campaign_id, char_id, spell_id, target, duration_turns),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify(
        character_id=char_id,
        concentration={
            "spell_id": spell_id,
            "target": target,
            "remaining_turns": duration_turns,
        },
    ), 200


@bp.get("/v1/play/campaigns/<campaign_id>/characters/<char_id>/concentration")
@require_auth
def get_play_campaign_character_concentration(username, _role, campaign_id, char_id):
    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        membership_error = _require_campaign_member(conn, campaign, username)
        if membership_error is not None:
            return membership_error

        owner_record = conn.execute(
            "SELECT 1 FROM play_character_owners "
            "WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, char_id),
        ).fetchone()
        if owner_record is None:
            return jsonify(error="character not found"), 404

        row = conn.execute(
            "SELECT spell_id, target, remaining_turns FROM play_character_concentration "
            "WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, char_id),
        ).fetchone()
    finally:
        conn.close()

    return jsonify(
        character_id=char_id,
        concentration=_serialize_concentration(row),
    ), 200


@bp.post("/v1/play/campaigns/<campaign_id>/characters/<char_id>/concentration/advance-turn")
@require_auth
def advance_play_campaign_character_concentration(username, _role, campaign_id, char_id):
    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        membership_error = _require_campaign_member(conn, campaign, username)
        if membership_error is not None:
            return membership_error

        owner_record = conn.execute(
            "SELECT 1 FROM play_character_owners "
            "WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, char_id),
        ).fetchone()
        if owner_record is None:
            return jsonify(error="character not found"), 404

        row = conn.execute(
            "SELECT spell_id, target, remaining_turns FROM play_character_concentration "
            "WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, char_id),
        ).fetchone()

        if row is not None:
            remaining = row["remaining_turns"] - 1
            if remaining <= 0:
                conn.execute(
                    "DELETE FROM play_character_concentration "
                    "WHERE campaign_id = ? AND character_id = ?",
                    (campaign_id, char_id),
                )
                row = None
            else:
                conn.execute(
                    "UPDATE play_character_concentration SET remaining_turns = ? "
                    "WHERE campaign_id = ? AND character_id = ?",
                    (remaining, campaign_id, char_id),
                )
                row = {"spell_id": row["spell_id"], "target": row["target"], "remaining_turns": remaining}
            conn.commit()
    finally:
        conn.close()

    return jsonify(
        character_id=char_id,
        concentration=_serialize_concentration(row),
    ), 200


@bp.delete("/v1/play/campaigns/<campaign_id>/characters/<char_id>/concentration")
@require_auth
def clear_play_campaign_character_concentration(username, _role, campaign_id, char_id):
    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        record = conn.execute(
            "SELECT owner FROM play_character_owners "
            "WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, char_id),
        ).fetchone()
        if record is None:
            return jsonify(error="character not found"), 404

        if record["owner"] != username:
            return jsonify(error="forbidden"), 403

        conn.execute(
            "DELETE FROM play_character_concentration "
            "WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, char_id),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify(character_id=char_id, concentration=None), 200


VALID_INVENTORY_ITEM_IDS = frozenset({
    "healing-potion",
    "torch",
    "leather-armor",
    "ring-of-protection",
    "amulet-of-health",
})

VALID_EQUIPMENT_SLOTS = frozenset({"armor", "accessory"})

CONSUMABLE_ITEM_IDS = frozenset({"healing-potion"})

CONSUMABLE_EFFECTS = {
    "healing-potion": {"type": "healing", "hp_restored": 5},
}

ITEM_SLOT_BY_ID = {
    "leather-armor": "armor",
    "ring-of-protection": "accessory",
    "amulet-of-health": "accessory",
}

ATTUNABLE_ITEM_IDS = frozenset({"ring-of-protection", "amulet-of-health"})

MAX_ATTUNEMENTS = 1


def _serialize_inventory_items(conn, campaign_id, char_id):
    rows = conn.execute(
        "SELECT item_id, quantity FROM play_character_inventory "
        "WHERE campaign_id = ? AND character_id = ? AND quantity > 0 "
        "ORDER BY item_id",
        (campaign_id, char_id),
    ).fetchall()
    return [{"item_id": row["item_id"], "quantity": row["quantity"]} for row in rows]


@bp.post("/v1/play/campaigns/<campaign_id>/characters/<char_id>/inventory/items")
@require_auth
def add_play_campaign_character_inventory_item(username, _role, campaign_id, char_id):
    data = request.get_json(silent=True) or {}
    item_id = data.get("item_id")
    quantity = data.get("quantity")

    if item_id not in VALID_INVENTORY_ITEM_IDS:
        return jsonify(error="invalid item_id"), 400
    if not valid_int(quantity) or quantity <= 0:
        return jsonify(error="invalid quantity"), 400

    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        record = conn.execute(
            "SELECT owner FROM play_character_owners "
            "WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, char_id),
        ).fetchone()
        if record is None:
            return jsonify(error="character not found"), 404

        if record["owner"] != username:
            return jsonify(error="forbidden"), 403

        existing = conn.execute(
            "SELECT quantity FROM play_character_inventory "
            "WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
            (campaign_id, char_id, item_id),
        ).fetchone()
        total_quantity = (existing["quantity"] if existing is not None else 0) + quantity

        conn.execute(
            "INSERT INTO play_character_inventory (campaign_id, character_id, item_id, quantity) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT (campaign_id, character_id, item_id) "
            "DO UPDATE SET quantity = excluded.quantity",
            (campaign_id, char_id, item_id, total_quantity),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify(
        character_id=char_id,
        item_id=item_id,
        quantity=quantity,
        total_quantity=total_quantity,
    ), 201


@bp.get("/v1/play/campaigns/<campaign_id>/characters/<char_id>/inventory/items")
@require_auth
def get_play_campaign_character_inventory_items(username, _role, campaign_id, char_id):
    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        membership_error = _require_campaign_member(conn, campaign, username)
        if membership_error is not None:
            return membership_error

        owner_record = conn.execute(
            "SELECT 1 FROM play_character_owners "
            "WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, char_id),
        ).fetchone()
        if owner_record is None:
            return jsonify(error="character not found"), 404

        items = _serialize_inventory_items(conn, campaign_id, char_id)
    finally:
        conn.close()

    return jsonify(character_id=char_id, items=items), 200


@bp.delete("/v1/play/campaigns/<campaign_id>/characters/<char_id>/inventory/items/<item_id>")
@require_auth
def remove_play_campaign_character_inventory_item(username, _role, campaign_id, char_id, item_id):
    data = request.get_json(silent=True) or {}
    quantity = data.get("quantity")

    if item_id not in VALID_INVENTORY_ITEM_IDS:
        return jsonify(error="invalid item_id"), 400
    if not valid_int(quantity) or quantity <= 0:
        return jsonify(error="invalid quantity"), 400

    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        record = conn.execute(
            "SELECT owner FROM play_character_owners "
            "WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, char_id),
        ).fetchone()
        if record is None:
            return jsonify(error="character not found"), 404

        if record["owner"] != username:
            return jsonify(error="forbidden"), 403

        existing = conn.execute(
            "SELECT quantity FROM play_character_inventory "
            "WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
            (campaign_id, char_id, item_id),
        ).fetchone()
        held_quantity = existing["quantity"] if existing is not None else 0

        if quantity > held_quantity:
            return jsonify(error="insufficient quantity"), 409

        total_quantity = held_quantity - quantity

        conn.execute(
            "INSERT INTO play_character_inventory (campaign_id, character_id, item_id, quantity) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT (campaign_id, character_id, item_id) "
            "DO UPDATE SET quantity = excluded.quantity",
            (campaign_id, char_id, item_id, total_quantity),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify(
        character_id=char_id,
        item_id=item_id,
        quantity=quantity,
        total_quantity=total_quantity,
    ), 200


def _serialize_equipment(char_id, slot, item_id, attuned):
    return {
        "character_id": char_id,
        "slot": slot,
        "item_id": item_id or "",
        "attuned": attuned,
    }


@bp.put("/v1/play/campaigns/<campaign_id>/characters/<char_id>/equipment/<slot>")
@require_auth
def put_play_campaign_character_equipment(username, _role, campaign_id, char_id, slot):
    data = request.get_json(silent=True) or {}
    item_id = data.get("item_id")

    if slot not in VALID_EQUIPMENT_SLOTS:
        return jsonify(error="invalid slot"), 400
    if item_id not in ITEM_SLOT_BY_ID:
        return jsonify(error="invalid item_id"), 400
    if ITEM_SLOT_BY_ID[item_id] != slot:
        return jsonify(error="item does not fit slot"), 400

    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        record = conn.execute(
            "SELECT owner FROM play_character_owners "
            "WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, char_id),
        ).fetchone()
        if record is None:
            return jsonify(error="character not found"), 404

        if record["owner"] != username:
            return jsonify(error="forbidden"), 403

        held = conn.execute(
            "SELECT quantity FROM play_character_inventory "
            "WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
            (campaign_id, char_id, item_id),
        ).fetchone()
        if held is None or held["quantity"] <= 0:
            return jsonify(error="item not held"), 400

        conn.execute(
            "INSERT INTO play_character_equipment (campaign_id, character_id, slot, item_id) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT (campaign_id, character_id, slot) "
            "DO UPDATE SET item_id = excluded.item_id",
            (campaign_id, char_id, slot, item_id),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify(_serialize_equipment(char_id, slot, item_id, False)), 200


@bp.get("/v1/play/campaigns/<campaign_id>/characters/<char_id>/equipment/<slot>")
@require_auth
def get_play_campaign_character_equipment(username, _role, campaign_id, char_id, slot):
    if slot not in VALID_EQUIPMENT_SLOTS:
        return jsonify(error="invalid slot"), 400

    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        membership_error = _require_campaign_member(conn, campaign, username)
        if membership_error is not None:
            return membership_error

        owner_record = conn.execute(
            "SELECT 1 FROM play_character_owners "
            "WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, char_id),
        ).fetchone()
        if owner_record is None:
            return jsonify(error="character not found"), 404

        equipped = conn.execute(
            "SELECT item_id FROM play_character_equipment "
            "WHERE campaign_id = ? AND character_id = ? AND slot = ?",
            (campaign_id, char_id, slot),
        ).fetchone()
        item_id = equipped["item_id"] if equipped is not None else ""

        attuned = False
        if item_id:
            attunement = conn.execute(
                "SELECT 1 FROM play_character_attunements "
                "WHERE campaign_id = ? AND character_id = ? AND slot = ? AND item_id = ?",
                (campaign_id, char_id, slot, item_id),
            ).fetchone()
            attuned = attunement is not None
    finally:
        conn.close()

    return jsonify(_serialize_equipment(char_id, slot, item_id, attuned)), 200


@bp.post("/v1/play/campaigns/<campaign_id>/characters/<char_id>/equipment/<slot>/attune")
@require_auth
def attune_play_campaign_character_equipment(username, _role, campaign_id, char_id, slot):
    if slot not in VALID_EQUIPMENT_SLOTS:
        return jsonify(error="invalid slot"), 400

    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        record = conn.execute(
            "SELECT owner FROM play_character_owners "
            "WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, char_id),
        ).fetchone()
        if record is None:
            return jsonify(error="character not found"), 404

        if record["owner"] != username:
            return jsonify(error="forbidden"), 403

        equipped = conn.execute(
            "SELECT item_id FROM play_character_equipment "
            "WHERE campaign_id = ? AND character_id = ? AND slot = ?",
            (campaign_id, char_id, slot),
        ).fetchone()
        item_id = equipped["item_id"] if equipped is not None else None
        if item_id is None or item_id not in ATTUNABLE_ITEM_IDS:
            return jsonify(error="slot has no attunable item equipped"), 400

        existing_count = conn.execute(
            "SELECT COUNT(*) AS cnt FROM play_character_attunements "
            "WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, char_id),
        ).fetchone()["cnt"]

        already_attuned = conn.execute(
            "SELECT 1 FROM play_character_attunements "
            "WHERE campaign_id = ? AND character_id = ? AND slot = ? AND item_id = ?",
            (campaign_id, char_id, slot, item_id),
        ).fetchone()
        if already_attuned is not None:
            return jsonify(error="already attuned"), 409

        if existing_count >= MAX_ATTUNEMENTS:
            return jsonify(error="max attunements reached"), 409

        conn.execute(
            "INSERT INTO play_character_attunements (campaign_id, character_id, slot, item_id) "
            "VALUES (?, ?, ?, ?)",
            (campaign_id, char_id, slot, item_id),
        )
        conn.commit()
        attunement_count = existing_count + 1
    finally:
        conn.close()

    return jsonify(
        character_id=char_id,
        slot=slot,
        item_id=item_id,
        attuned=True,
        attunement_count=attunement_count,
        max_attunements=MAX_ATTUNEMENTS,
    ), 200


@bp.post("/v1/play/campaigns/<campaign_id>/characters/<char_id>/inventory/items/<item_id>/consume")
@require_auth
def consume_play_campaign_character_inventory_item(username, _role, campaign_id, char_id, item_id):
    if item_id not in VALID_INVENTORY_ITEM_IDS:
        return jsonify(error="invalid item_id"), 400
    if item_id not in CONSUMABLE_ITEM_IDS:
        return jsonify(error="item not consumable"), 400

    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        record = conn.execute(
            "SELECT owner FROM play_character_owners "
            "WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, char_id),
        ).fetchone()
        if record is None:
            return jsonify(error="character not found"), 404

        if record["owner"] != username:
            return jsonify(error="forbidden"), 403

        existing = conn.execute(
            "SELECT quantity FROM play_character_inventory "
            "WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
            (campaign_id, char_id, item_id),
        ).fetchone()
        held_quantity = existing["quantity"] if existing is not None else 0

        if held_quantity <= 0:
            return jsonify(error="item not held"), 409

        total_quantity = held_quantity - 1

        conn.execute(
            "INSERT INTO play_character_inventory (campaign_id, character_id, item_id, quantity) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT (campaign_id, character_id, item_id) "
            "DO UPDATE SET quantity = excluded.quantity",
            (campaign_id, char_id, item_id, total_quantity),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify(
        character_id=char_id,
        item_id=item_id,
        quantity_consumed=1,
        total_quantity=total_quantity,
        effect=CONSUMABLE_EFFECTS[item_id],
    ), 200


@bp.get("/v1/play/campaigns/<campaign_id>/characters/<char_id>/currency")
@require_auth
def get_play_campaign_character_currency(username, _role, campaign_id, char_id):
    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        membership_error = _require_campaign_member(conn, campaign, username)
        if membership_error is not None:
            return membership_error

        record = conn.execute(
            "SELECT gold FROM play_character_currency "
            "WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, char_id),
        ).fetchone()
        if record is None:
            return jsonify(error="character not found"), 404
    finally:
        conn.close()

    return jsonify(character_id=char_id, gold=record["gold"]), 200


@bp.post("/v1/play/campaigns/<campaign_id>/characters/<char_id>/currency/transfers")
@require_auth
def transfer_play_campaign_character_currency(username, _role, campaign_id, char_id):
    data = request.get_json(silent=True) or {}
    to_character_id = data.get("to_character_id")
    gold = data.get("gold")

    if not isinstance(to_character_id, str) or not to_character_id:
        return jsonify(error="invalid to_character_id"), 400
    if not valid_int(gold):
        return jsonify(error="invalid gold"), 400

    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        membership_error = _require_campaign_member(conn, campaign, username)
        if membership_error is not None:
            return membership_error

        owner_record = conn.execute(
            "SELECT owner FROM play_character_owners "
            "WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, char_id),
        ).fetchone()
        if owner_record is None:
            return jsonify(error="character not found"), 404

        if owner_record["owner"] != username:
            return jsonify(error="forbidden"), 403

        if char_id == to_character_id:
            return jsonify(error="invalid to_character_id"), 400

        destination_exists = conn.execute(
            "SELECT 1 FROM play_character_owners "
            "WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, to_character_id),
        ).fetchone()
        if destination_exists is None:
            return jsonify(error="invalid to_character_id"), 400

        if gold <= 0:
            return jsonify(error="invalid gold"), 400

        source_currency = conn.execute(
            "SELECT gold FROM play_character_currency "
            "WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, char_id),
        ).fetchone()
        source_gold = source_currency["gold"] if source_currency is not None else 0

        if source_gold < gold:
            return jsonify(error="insufficient gold"), 409

        destination_currency = conn.execute(
            "SELECT gold FROM play_character_currency "
            "WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, to_character_id),
        ).fetchone()
        destination_gold = destination_currency["gold"] if destination_currency is not None else 0

        from_gold = source_gold - gold
        to_gold = destination_gold + gold

        conn.execute(
            "INSERT INTO play_character_currency (campaign_id, character_id, gold) "
            "VALUES (?, ?, ?) "
            "ON CONFLICT (campaign_id, character_id) "
            "DO UPDATE SET gold = excluded.gold",
            (campaign_id, char_id, from_gold),
        )
        conn.execute(
            "INSERT INTO play_character_currency (campaign_id, character_id, gold) "
            "VALUES (?, ?, ?) "
            "ON CONFLICT (campaign_id, character_id) "
            "DO UPDATE SET gold = excluded.gold",
            (campaign_id, to_character_id, to_gold),
        )

        last_transfer_id = conn.execute(
            "SELECT MAX(transfer_id) AS t FROM play_currency_transfers WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()["t"]
        transfer_id = (last_transfer_id or 0) + 1

        conn.execute(
            "INSERT INTO play_currency_transfers "
            "(campaign_id, transfer_id, from_character_id, to_character_id, gold) "
            "VALUES (?, ?, ?, ?, ?)",
            (campaign_id, transfer_id, char_id, to_character_id, gold),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify(
        from_character_id=char_id,
        to_character_id=to_character_id,
        gold=gold,
        from_gold=from_gold,
        to_gold=to_gold,
        transfer_id=transfer_id,
    ), 201


@bp.post("/v1/play/campaigns/<campaign_id>/loot")
@require_auth
def create_play_campaign_loot(username, _role, campaign_id):
    data = request.get_json(silent=True) or {}
    loot_id = data.get("loot_id")
    item_id = data.get("item_id")
    quantity = data.get("quantity")

    if not isinstance(loot_id, str) or not loot_id:
        return jsonify(error="invalid loot_id"), 400
    if item_id not in VALID_INVENTORY_ITEM_IDS:
        return jsonify(error="invalid item_id"), 400
    if not valid_int(quantity) or quantity <= 0:
        return jsonify(error="invalid quantity"), 400

    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        if campaign["owner"] != username:
            return jsonify(error="forbidden"), 403

        existing = conn.execute(
            "SELECT loot_id FROM play_loot WHERE campaign_id = ? AND loot_id = ?",
            (campaign_id, loot_id),
        ).fetchone()
        if existing is not None:
            return jsonify(error="loot already exists"), 409

        conn.execute(
            "INSERT INTO play_loot "
            "(campaign_id, loot_id, item_id, quantity, status, recipient_character_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (campaign_id, loot_id, item_id, quantity, "open", None),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify(
        loot_id=loot_id,
        item_id=item_id,
        quantity=quantity,
        status="open",
    ), 201


@bp.post("/v1/play/campaigns/<campaign_id>/loot/<loot_id>/votes")
@require_auth
def cast_play_campaign_loot_vote(username, role, campaign_id, loot_id):
    if role != "player":
        return jsonify(error="forbidden"), 403

    data = request.get_json(silent=True) or {}
    recipient_character_id = data.get("recipient_character_id")

    if not isinstance(recipient_character_id, str) or not recipient_character_id:
        return jsonify(error="invalid recipient_character_id"), 400

    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        membership_error = _require_campaign_member(conn, campaign, username)
        if membership_error is not None:
            return membership_error

        loot = conn.execute(
            "SELECT loot_id FROM play_loot WHERE campaign_id = ? AND loot_id = ?",
            (campaign_id, loot_id),
        ).fetchone()
        if loot is None:
            return jsonify(error="loot not found"), 404

        recipient_exists = conn.execute(
            "SELECT 1 FROM play_character_owners "
            "WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, recipient_character_id),
        ).fetchone()
        if recipient_exists is None:
            return jsonify(error="invalid recipient_character_id"), 400

        existing_vote = conn.execute(
            "SELECT recipient_character_id FROM play_loot_votes "
            "WHERE campaign_id = ? AND loot_id = ? AND voter = ?",
            (campaign_id, loot_id, username),
        ).fetchone()
        if existing_vote is not None:
            return jsonify(error="already voted"), 409

        conn.execute(
            "INSERT INTO play_loot_votes (campaign_id, loot_id, voter, recipient_character_id) "
            "VALUES (?, ?, ?, ?)",
            (campaign_id, loot_id, username, recipient_character_id),
        )

        votes_for_recipient = conn.execute(
            "SELECT COUNT(*) AS c FROM play_loot_votes "
            "WHERE campaign_id = ? AND loot_id = ? AND recipient_character_id = ?",
            (campaign_id, loot_id, recipient_character_id),
        ).fetchone()["c"]
        conn.commit()
    finally:
        conn.close()

    return jsonify(
        loot_id=loot_id,
        voter=username,
        recipient_character_id=recipient_character_id,
        votes_for_recipient=votes_for_recipient,
    ), 201


@bp.post("/v1/play/campaigns/<campaign_id>/loot/<loot_id>/assign")
@require_auth
def assign_play_campaign_loot(username, _role, campaign_id, loot_id):
    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        if campaign["owner"] != username:
            return jsonify(error="forbidden"), 403

        loot = conn.execute(
            "SELECT loot_id, item_id, quantity, status FROM play_loot "
            "WHERE campaign_id = ? AND loot_id = ?",
            (campaign_id, loot_id),
        ).fetchone()
        if loot is None:
            return jsonify(error="loot not found"), 404

        if loot["status"] != "open":
            return jsonify(error="loot not open"), 409

        tallies = conn.execute(
            "SELECT recipient_character_id, COUNT(*) AS c FROM play_loot_votes "
            "WHERE campaign_id = ? AND loot_id = ? "
            "GROUP BY recipient_character_id ORDER BY c DESC",
            (campaign_id, loot_id),
        ).fetchall()
        if not tallies:
            return jsonify(error="no votes cast"), 409
        if len(tallies) > 1 and tallies[0]["c"] == tallies[1]["c"]:
            return jsonify(error="tied vote"), 409

        recipient_character_id = tallies[0]["recipient_character_id"]
        vote_count = tallies[0]["c"]

        existing_inventory = conn.execute(
            "SELECT quantity FROM play_character_inventory "
            "WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
            (campaign_id, recipient_character_id, loot["item_id"]),
        ).fetchone()
        total_quantity = (existing_inventory["quantity"] if existing_inventory is not None else 0) + loot["quantity"]

        conn.execute(
            "INSERT INTO play_character_inventory (campaign_id, character_id, item_id, quantity) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT (campaign_id, character_id, item_id) "
            "DO UPDATE SET quantity = excluded.quantity",
            (campaign_id, recipient_character_id, loot["item_id"], total_quantity),
        )

        conn.execute(
            "UPDATE play_loot SET status = ?, recipient_character_id = ? "
            "WHERE campaign_id = ? AND loot_id = ?",
            ("assigned", recipient_character_id, campaign_id, loot_id),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify(
        loot_id=loot_id,
        recipient_character_id=recipient_character_id,
        item_id=loot["item_id"],
        quantity=loot["quantity"],
        votes=vote_count,
        status="assigned",
    ), 200


@bp.get("/v1/play/campaigns/<campaign_id>/loot/<loot_id>")
@require_auth
def get_play_campaign_loot(username, _role, campaign_id, loot_id):
    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        membership_error = _require_campaign_member(conn, campaign, username)
        if membership_error is not None:
            return membership_error

        loot = conn.execute(
            "SELECT loot_id, item_id, quantity, status, recipient_character_id "
            "FROM play_loot WHERE campaign_id = ? AND loot_id = ?",
            (campaign_id, loot_id),
        ).fetchone()
        if loot is None:
            return jsonify(error="loot not found"), 404

        vote_rows = conn.execute(
            "SELECT recipient_character_id, COUNT(*) AS c FROM play_loot_votes "
            "WHERE campaign_id = ? AND loot_id = ? GROUP BY recipient_character_id",
            (campaign_id, loot_id),
        ).fetchall()
    finally:
        conn.close()

    votes = {row["recipient_character_id"]: row["c"] for row in vote_rows}

    return jsonify(
        loot_id=loot["loot_id"],
        item_id=loot["item_id"],
        quantity=loot["quantity"],
        status=loot["status"],
        recipient_character_id=loot["recipient_character_id"],
        votes=votes,
    ), 200


@bp.post("/v1/play/campaigns/<campaign_id>/npcs")
@require_auth
def create_play_campaign_npc(username, _role, campaign_id):
    data = request.get_json(silent=True) or {}
    npc_id = data.get("npc_id")
    name = data.get("name")
    agenda = data.get("agenda")
    public_status = data.get("public_status")

    if not valid_nonempty_str(npc_id):
        return jsonify(error="invalid npc_id"), 400
    if not valid_nonempty_str(name):
        return jsonify(error="invalid name"), 400
    if not valid_nonempty_str(agenda):
        return jsonify(error="invalid agenda"), 400
    if not valid_nonempty_str(public_status):
        return jsonify(error="invalid public_status"), 400

    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        if campaign["owner"] != username:
            return jsonify(error="forbidden"), 403

        existing = conn.execute(
            "SELECT npc_id FROM play_npcs WHERE campaign_id = ? AND npc_id = ?",
            (campaign_id, npc_id),
        ).fetchone()
        if existing is not None:
            return jsonify(error="npc already exists"), 409

        conn.execute(
            "INSERT INTO play_npcs (campaign_id, npc_id, name, agenda, public_status) "
            "VALUES (?, ?, ?, ?, ?)",
            (campaign_id, npc_id, name, agenda, public_status),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify(
        npc_id=npc_id,
        name=name,
        agenda=agenda,
        public_status=public_status,
    ), 201


@bp.put("/v1/play/campaigns/<campaign_id>/npcs/<npc_id>/agenda")
@require_auth
def update_play_campaign_npc_agenda(username, _role, campaign_id, npc_id):
    data = request.get_json(silent=True) or {}
    agenda = data.get("agenda")
    public_status = data.get("public_status")

    if not valid_nonempty_str(agenda):
        return jsonify(error="invalid agenda"), 400
    if not valid_nonempty_str(public_status):
        return jsonify(error="invalid public_status"), 400

    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        if campaign["owner"] != username:
            return jsonify(error="forbidden"), 403

        npc = conn.execute(
            "SELECT npc_id FROM play_npcs WHERE campaign_id = ? AND npc_id = ?",
            (campaign_id, npc_id),
        ).fetchone()
        if npc is None:
            return jsonify(error="npc not found"), 404

        conn.execute(
            "UPDATE play_npcs SET agenda = ?, public_status = ? "
            "WHERE campaign_id = ? AND npc_id = ?",
            (agenda, public_status, campaign_id, npc_id),
        )

        name = conn.execute(
            "SELECT name FROM play_npcs WHERE campaign_id = ? AND npc_id = ?",
            (campaign_id, npc_id),
        ).fetchone()["name"]
        conn.commit()
    finally:
        conn.close()

    return jsonify(
        npc_id=npc_id,
        name=name,
        agenda=agenda,
        public_status=public_status,
    ), 200


@bp.get("/v1/play/campaigns/<campaign_id>/npcs/<npc_id>")
@require_auth
def get_play_campaign_npc(username, _role, campaign_id, npc_id):
    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        membership_error = _require_campaign_member(conn, campaign, username)
        if membership_error is not None:
            return membership_error

        npc = conn.execute(
            "SELECT npc_id, name, agenda, public_status FROM play_npcs "
            "WHERE campaign_id = ? AND npc_id = ?",
            (campaign_id, npc_id),
        ).fetchone()
        if npc is None:
            return jsonify(error="npc not found"), 404
    finally:
        conn.close()

    if campaign["owner"] == username:
        return jsonify(
            npc_id=npc["npc_id"],
            name=npc["name"],
            agenda=npc["agenda"],
            public_status=npc["public_status"],
        ), 200

    return jsonify(
        npc_id=npc["npc_id"],
        name=npc["name"],
        public_status=npc["public_status"],
    ), 200


@bp.post("/v1/play/campaigns/<campaign_id>/factions")
@require_auth
def create_play_campaign_faction(username, _role, campaign_id):
    data = request.get_json(silent=True) or {}
    faction_id = data.get("faction_id")
    name = data.get("name")

    if not valid_nonempty_str(faction_id):
        return jsonify(error="invalid faction_id"), 400
    if not valid_nonempty_str(name):
        return jsonify(error="invalid name"), 400

    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        if campaign["owner"] != username:
            return jsonify(error="forbidden"), 403

        existing = conn.execute(
            "SELECT faction_id FROM play_factions WHERE campaign_id = ? AND faction_id = ?",
            (campaign_id, faction_id),
        ).fetchone()
        if existing is not None:
            return jsonify(error="faction already exists"), 409

        conn.execute(
            "INSERT INTO play_factions (campaign_id, faction_id, name) VALUES (?, ?, ?)",
            (campaign_id, faction_id, name),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify(faction_id=faction_id, name=name), 201


@bp.post("/v1/play/campaigns/<campaign_id>/factions/<faction_id>/reputation")
@require_auth
def create_play_campaign_faction_reputation(username, _role, campaign_id, faction_id):
    data = request.get_json(silent=True) or {}
    character_id = data.get("character_id")
    delta = data.get("delta")
    reason = data.get("reason")

    if not valid_nonempty_str(character_id):
        return jsonify(error="invalid character_id"), 400
    if not valid_int_in_range(delta, -25, 25) or delta == 0:
        return jsonify(error="invalid delta"), 400
    if not valid_nonempty_str(reason):
        return jsonify(error="invalid reason"), 400

    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        if campaign["owner"] != username:
            return jsonify(error="forbidden"), 403

        faction = conn.execute(
            "SELECT faction_id FROM play_factions WHERE campaign_id = ? AND faction_id = ?",
            (campaign_id, faction_id),
        ).fetchone()
        if faction is None:
            return jsonify(error="faction not found"), 404

        member = conn.execute(
            "SELECT 1 FROM play_members WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, character_id),
        ).fetchone()
        if member is None:
            return jsonify(error="character not found"), 400

        last = conn.execute(
            "SELECT reputation FROM play_faction_reputation "
            "WHERE campaign_id = ? AND faction_id = ? AND character_id = ? "
            "ORDER BY id DESC LIMIT 1",
            (campaign_id, faction_id, character_id),
        ).fetchone()
        previous = last["reputation"] if last is not None else 0
        reputation = max(-100, min(100, previous + delta))

        conn.execute(
            "INSERT INTO play_faction_reputation "
            "(campaign_id, faction_id, character_id, delta, reason, reputation) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (campaign_id, faction_id, character_id, delta, reason, reputation),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify(
        faction_id=faction_id,
        character_id=character_id,
        reputation=reputation,
        delta=delta,
        reason=reason,
    ), 201


@bp.get("/v1/play/campaigns/<campaign_id>/factions/<faction_id>/reputation")
@require_auth
def get_play_campaign_faction_reputation(username, _role, campaign_id, faction_id):
    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        membership_error = _require_campaign_member(conn, campaign, username)
        if membership_error is not None:
            return membership_error

        faction = conn.execute(
            "SELECT faction_id FROM play_factions WHERE campaign_id = ? AND faction_id = ?",
            (campaign_id, faction_id),
        ).fetchone()
        if faction is None:
            return jsonify(error="faction not found"), 404

        if campaign["owner"] == username:
            rows = conn.execute(
                "SELECT faction_id, character_id, reputation, delta, reason "
                "FROM play_faction_reputation "
                "WHERE campaign_id = ? AND faction_id = ? ORDER BY id ASC",
                (campaign_id, faction_id),
            ).fetchall()
        else:
            own_character = conn.execute(
                "SELECT character_id FROM play_members WHERE campaign_id = ? AND username = ?",
                (campaign_id, username),
            ).fetchone()
            character_id = own_character["character_id"] if own_character is not None else None
            rows = conn.execute(
                "SELECT faction_id, character_id, reputation, delta, reason "
                "FROM play_faction_reputation "
                "WHERE campaign_id = ? AND faction_id = ? AND character_id = ? ORDER BY id ASC",
                (campaign_id, faction_id, character_id),
            ).fetchall()
    finally:
        conn.close()

    entries = [
        {
            "faction_id": row["faction_id"],
            "character_id": row["character_id"],
            "reputation": row["reputation"],
            "delta": row["delta"],
            "reason": row["reason"],
        }
        for row in rows
    ]

    return jsonify(faction_id=faction_id, entries=entries), 200


@bp.post("/v1/play/campaigns/<campaign_id>/npcs/<npc_id>/dialogue")
@require_auth
def create_play_campaign_npc_dialogue(username, _role, campaign_id, npc_id):
    data = request.get_json(silent=True) or {}
    dialogue_id = data.get("dialogue_id")
    speaker = data.get("speaker")
    text = data.get("text")
    visibility = data.get("visibility")

    if not valid_nonempty_str(dialogue_id):
        return jsonify(error="invalid dialogue_id"), 400
    if not valid_nonempty_str(speaker):
        return jsonify(error="invalid speaker"), 400
    if not valid_nonempty_str(text):
        return jsonify(error="invalid text"), 400
    if visibility not in ("public", "private"):
        return jsonify(error="invalid visibility"), 400

    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        npc = conn.execute(
            "SELECT npc_id FROM play_npcs WHERE campaign_id = ? AND npc_id = ?",
            (campaign_id, npc_id),
        ).fetchone()
        if npc is None:
            return jsonify(error="npc not found"), 404

        if campaign["owner"] != username:
            return jsonify(error="forbidden"), 403

        existing = conn.execute(
            "SELECT id FROM play_npc_dialogue "
            "WHERE campaign_id = ? AND npc_id = ? AND dialogue_id = ?",
            (campaign_id, npc_id, dialogue_id),
        ).fetchone()
        if existing is not None:
            return jsonify(error="dialogue already exists"), 409

        conn.execute(
            "INSERT INTO play_npc_dialogue "
            "(campaign_id, npc_id, dialogue_id, speaker, text, visibility) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (campaign_id, npc_id, dialogue_id, speaker, text, visibility),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify(
        dialogue_id=dialogue_id,
        speaker=speaker,
        text=text,
        visibility=visibility,
    ), 201


@bp.get("/v1/play/campaigns/<campaign_id>/npcs/<npc_id>/dialogue")
@require_auth
def get_play_campaign_npc_dialogue(username, _role, campaign_id, npc_id):
    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        membership_error = _require_campaign_member(conn, campaign, username)
        if membership_error is not None:
            return membership_error

        npc = conn.execute(
            "SELECT npc_id FROM play_npcs WHERE campaign_id = ? AND npc_id = ?",
            (campaign_id, npc_id),
        ).fetchone()
        if npc is None:
            return jsonify(error="npc not found"), 404

        rows = conn.execute(
            "SELECT dialogue_id, speaker, text, visibility FROM play_npc_dialogue "
            "WHERE campaign_id = ? AND npc_id = ? ORDER BY id ASC",
            (campaign_id, npc_id),
        ).fetchall()
    finally:
        conn.close()

    is_dm = campaign["owner"] == username
    entries = [
        {
            "dialogue_id": row["dialogue_id"],
            "speaker": row["speaker"],
            "text": row["text"],
            "visibility": row["visibility"],
        }
        for row in rows
        if is_dm or row["visibility"] == "public"
    ]

    return jsonify(npc_id=npc_id, entries=entries), 200


def _campaign_entity_exists(conn, campaign_id, entity_id):
    member = conn.execute(
        "SELECT 1 FROM play_members WHERE campaign_id = ? AND character_id = ?",
        (campaign_id, entity_id),
    ).fetchone()
    if member is not None:
        return True
    npc = conn.execute(
        "SELECT 1 FROM play_npcs WHERE campaign_id = ? AND npc_id = ?",
        (campaign_id, entity_id),
    ).fetchone()
    return npc is not None


def _serialize_relationship(row):
    return {
        "source_id": row["source_id"],
        "target_id": row["target_id"],
        "kind": row["kind"],
        "score": row["score"],
    }


@bp.post("/v1/play/campaigns/<campaign_id>/relationships")
@require_auth
def create_play_campaign_relationship(username, _role, campaign_id):
    data = request.get_json(silent=True) or {}
    source_id = data.get("source_id")
    target_id = data.get("target_id")
    kind = data.get("kind")
    score = data.get("score")

    if not valid_nonempty_str(source_id):
        return jsonify(error="invalid source_id"), 400
    if not valid_nonempty_str(target_id):
        return jsonify(error="invalid target_id"), 400
    if source_id == target_id:
        return jsonify(error="invalid self-edge"), 400
    if not valid_nonempty_str(kind):
        return jsonify(error="invalid kind"), 400
    if not valid_int_in_range(score, -100, 100):
        return jsonify(error="invalid score"), 400

    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        if campaign["owner"] != username:
            return jsonify(error="forbidden"), 403

        if not _campaign_entity_exists(conn, campaign_id, source_id):
            return jsonify(error="source_id not found"), 404
        if not _campaign_entity_exists(conn, campaign_id, target_id):
            return jsonify(error="target_id not found"), 404

        existing = conn.execute(
            "SELECT id FROM play_relationships "
            "WHERE campaign_id = ? AND source_id = ? AND target_id = ? AND kind = ?",
            (campaign_id, source_id, target_id, kind),
        ).fetchone()
        if existing is not None:
            return jsonify(error="relationship already exists"), 409

        conn.execute(
            "INSERT INTO play_relationships "
            "(campaign_id, source_id, target_id, kind, score) "
            "VALUES (?, ?, ?, ?, ?)",
            (campaign_id, source_id, target_id, kind, score),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify(
        source_id=source_id,
        target_id=target_id,
        kind=kind,
        score=score,
    ), 201


@bp.put(
    "/v1/play/campaigns/<campaign_id>/relationships/<source_id>/<target_id>/<kind>"
)
@require_auth
def update_play_campaign_relationship(
    username, _role, campaign_id, source_id, target_id, kind
):
    data = request.get_json(silent=True) or {}
    score = data.get("score")

    if not valid_int_in_range(score, -100, 100):
        return jsonify(error="invalid score"), 400

    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        if campaign["owner"] != username:
            return jsonify(error="forbidden"), 403

        existing = conn.execute(
            "SELECT id FROM play_relationships "
            "WHERE campaign_id = ? AND source_id = ? AND target_id = ? AND kind = ?",
            (campaign_id, source_id, target_id, kind),
        ).fetchone()
        if existing is None:
            return jsonify(error="relationship not found"), 404

        conn.execute(
            "UPDATE play_relationships SET score = ? WHERE id = ?",
            (score, existing["id"]),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify(
        source_id=source_id,
        target_id=target_id,
        kind=kind,
        score=score,
    ), 200


@bp.get("/v1/play/campaigns/<campaign_id>/relationships")
@require_auth
def get_play_campaign_relationships(username, _role, campaign_id):
    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        membership_error = _require_campaign_member(conn, campaign, username)
        if membership_error is not None:
            return membership_error

        rows = conn.execute(
            "SELECT source_id, target_id, kind, score FROM play_relationships "
            "WHERE campaign_id = ? ORDER BY id ASC",
            (campaign_id,),
        ).fetchall()
    finally:
        conn.close()

    return jsonify(edges=[_serialize_relationship(row) for row in rows]), 200


VALID_CLUE_AUDIENCES = ("character", "party", "hidden")


def _serialize_clue(row):
    clue = {
        "clue_id": row["clue_id"],
        "text": row["text"],
        "audience": row["audience"],
    }
    if row["audience"] == "character":
        clue["character_id"] = row["character_id"]
    return clue


@bp.post("/v1/play/campaigns/<campaign_id>/clues")
@require_auth
def create_play_campaign_clue(username, _role, campaign_id):
    data = request.get_json(silent=True) or {}
    clue_id = data.get("clue_id")
    text = data.get("text")
    audience = data.get("audience")
    character_id = data.get("character_id")

    if not valid_nonempty_str(clue_id):
        return jsonify(error="invalid clue_id"), 400
    if not valid_nonempty_str(text):
        return jsonify(error="invalid text"), 400
    if audience not in VALID_CLUE_AUDIENCES:
        return jsonify(error="invalid audience"), 400
    if audience == "character":
        if not valid_nonempty_str(character_id):
            return jsonify(error="character_id required"), 400
    else:
        if character_id is not None:
            return jsonify(error="character_id not allowed"), 400

    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        if campaign["owner"] != username:
            return jsonify(error="forbidden"), 403

        if audience == "character":
            member = conn.execute(
                "SELECT 1 FROM play_members WHERE campaign_id = ? AND character_id = ?",
                (campaign_id, character_id),
            ).fetchone()
            if member is None:
                return jsonify(error="character_id not found"), 400

        existing = conn.execute(
            "SELECT id FROM play_clues WHERE campaign_id = ? AND clue_id = ?",
            (campaign_id, clue_id),
        ).fetchone()
        if existing is not None:
            return jsonify(error="clue already exists"), 409

        conn.execute(
            "INSERT INTO play_clues "
            "(campaign_id, clue_id, text, audience, character_id) "
            "VALUES (?, ?, ?, ?, ?)",
            (campaign_id, clue_id, text, audience, character_id),
        )
        conn.commit()
    finally:
        conn.close()

    response = {"clue_id": clue_id, "text": text, "audience": audience}
    if audience == "character":
        response["character_id"] = character_id
    return jsonify(**response), 201


@bp.get("/v1/play/campaigns/<campaign_id>/clues")
@require_auth
def get_play_campaign_clues(username, _role, campaign_id):
    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        membership_error = _require_campaign_member(conn, campaign, username)
        if membership_error is not None:
            return membership_error

        is_dm = campaign["owner"] == username
        own_character_id = None
        if not is_dm:
            member = conn.execute(
                "SELECT character_id FROM play_members "
                "WHERE campaign_id = ? AND username = ?",
                (campaign_id, username),
            ).fetchone()
            own_character_id = member["character_id"] if member else None

        rows = conn.execute(
            "SELECT clue_id, text, audience, character_id FROM play_clues "
            "WHERE campaign_id = ? ORDER BY id ASC",
            (campaign_id,),
        ).fetchall()
    finally:
        conn.close()

    clues = []
    for row in rows:
        if is_dm:
            clues.append(_serialize_clue(row))
            continue
        if row["audience"] == "party":
            clues.append(_serialize_clue(row))
        elif row["audience"] == "character" and row["character_id"] == own_character_id:
            clues.append(_serialize_clue(row))

    return jsonify(clues=clues), 200


def _serialize_quest(row):
    return {
        "quest_id": row["quest_id"],
        "title": row["title"],
        "depends_on": json.loads(row["depends_on"]),
        "state": row["state"],
    }


@bp.post("/v1/play/campaigns/<campaign_id>/quests")
@require_auth
def create_play_campaign_quest(username, _role, campaign_id):
    data = request.get_json(silent=True) or {}
    quest_id = data.get("quest_id")
    title = data.get("title")
    depends_on = data.get("depends_on", [])

    if not valid_nonempty_str(quest_id):
        return jsonify(error="invalid quest_id"), 400
    if not valid_nonempty_str(title):
        return jsonify(error="invalid title"), 400
    if not isinstance(depends_on, list) or not all(
        isinstance(dep, str) for dep in depends_on
    ):
        return jsonify(error="invalid depends_on"), 400
    if len(set(depends_on)) != len(depends_on):
        return jsonify(error="invalid depends_on"), 400
    if quest_id in depends_on:
        return jsonify(error="invalid depends_on"), 400

    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        if campaign["owner"] != username:
            return jsonify(error="forbidden"), 403

        if depends_on:
            existing_ids = {
                row["quest_id"]
                for row in conn.execute(
                    "SELECT quest_id FROM play_quests WHERE campaign_id = ?",
                    (campaign_id,),
                ).fetchall()
            }
            if not set(depends_on).issubset(existing_ids):
                return jsonify(error="invalid depends_on"), 400

        existing = conn.execute(
            "SELECT id FROM play_quests WHERE campaign_id = ? AND quest_id = ?",
            (campaign_id, quest_id),
        ).fetchone()
        if existing is not None:
            return jsonify(error="quest already exists"), 409

        conn.execute(
            "INSERT INTO play_quests "
            "(campaign_id, quest_id, title, depends_on, state) "
            "VALUES (?, ?, ?, ?, ?)",
            (campaign_id, quest_id, title, json.dumps(depends_on), "locked"),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify(
        quest_id=quest_id, title=title, depends_on=depends_on, state="locked"
    ), 201


@bp.put("/v1/play/campaigns/<campaign_id>/quests/<quest_id>/state")
@require_auth
def update_play_campaign_quest_state(username, _role, campaign_id, quest_id):
    data = request.get_json(silent=True) or {}
    new_state = data.get("state")

    if new_state not in ("active", "completed"):
        return jsonify(error="invalid state"), 400

    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        if campaign["owner"] != username:
            return jsonify(error="forbidden"), 403

        quest = conn.execute(
            "SELECT id, quest_id, title, depends_on, state FROM play_quests "
            "WHERE campaign_id = ? AND quest_id = ?",
            (campaign_id, quest_id),
        ).fetchone()
        if quest is None:
            return jsonify(error="quest not found"), 404

        current_state = quest["state"]
        if current_state == "locked" and new_state == "active":
            depends_on = json.loads(quest["depends_on"])
            if depends_on:
                placeholders = ",".join("?" for _ in depends_on)
                dep_rows = conn.execute(
                    f"SELECT quest_id, state FROM play_quests "
                    f"WHERE campaign_id = ? AND quest_id IN ({placeholders})",
                    (campaign_id, *depends_on),
                ).fetchall()
                dep_states = {row["quest_id"]: row["state"] for row in dep_rows}
                if any(
                    dep_states.get(dep) != "completed" for dep in depends_on
                ):
                    return jsonify(error="prerequisites not completed"), 409
        elif current_state == "active" and new_state == "completed":
            pass
        else:
            return jsonify(error="invalid transition"), 409

        conn.execute(
            "UPDATE play_quests SET state = ? WHERE id = ?",
            (new_state, quest["id"]),
        )
        conn.commit()

        title = quest["title"]
        depends_on = json.loads(quest["depends_on"])

        reward = conn.execute(
            "SELECT xp, items_json FROM play_quest_rewards "
            "WHERE campaign_id = ? AND quest_id = ?",
            (campaign_id, quest_id),
        ).fetchone()
    finally:
        conn.close()

    response = dict(
        quest_id=quest_id, title=title, depends_on=depends_on, state=new_state
    )
    if reward is not None:
        response["rewards"] = {"xp": reward["xp"], "items": json.loads(reward["items_json"])}

    return jsonify(**response), 200


@bp.get("/v1/play/campaigns/<campaign_id>/quests")
@require_auth
def get_play_campaign_quests(username, _role, campaign_id):
    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        membership_error = _require_campaign_member(conn, campaign, username)
        if membership_error is not None:
            return membership_error

        rows = conn.execute(
            "SELECT quest_id, title, depends_on, state FROM play_quests "
            "WHERE campaign_id = ? ORDER BY id ASC",
            (campaign_id,),
        ).fetchall()
    finally:
        conn.close()

    return jsonify(quests=[_serialize_quest(row) for row in rows]), 200


def _valid_reward_items(items):
    if not isinstance(items, dict):
        return False
    for item_id, quantity in items.items():
        if item_id not in VALID_INVENTORY_ITEM_IDS:
            return False
        if not valid_int(quantity) or quantity <= 0:
            return False
    return True


@bp.put("/v1/play/campaigns/<campaign_id>/quests/<quest_id>/rewards")
@require_auth
def configure_play_campaign_quest_rewards(username, _role, campaign_id, quest_id):
    data = request.get_json(silent=True) or {}
    xp = data.get("xp")
    items = data.get("items", {})

    if not valid_int(xp) or xp < 0:
        return jsonify(error="invalid xp"), 400
    if not _valid_reward_items(items):
        return jsonify(error="invalid items"), 400

    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        if campaign["owner"] != username:
            return jsonify(error="forbidden"), 403

        quest = conn.execute(
            "SELECT id, quest_id, title, depends_on, state FROM play_quests "
            "WHERE campaign_id = ? AND quest_id = ?",
            (campaign_id, quest_id),
        ).fetchone()
        if quest is None:
            return jsonify(error="quest not found"), 404

        if quest["state"] not in ("locked", "active"):
            return jsonify(error="quest already completed"), 409

        conn.execute(
            "INSERT INTO play_quest_rewards (campaign_id, quest_id, xp, items_json, awarded) "
            "VALUES (?, ?, ?, ?, 0) "
            "ON CONFLICT (campaign_id, quest_id) "
            "DO UPDATE SET xp = excluded.xp, items_json = excluded.items_json",
            (campaign_id, quest_id, xp, json.dumps(items)),
        )
        conn.commit()

        title = quest["title"]
        depends_on = json.loads(quest["depends_on"])
        state = quest["state"]
    finally:
        conn.close()

    return jsonify(
        quest_id=quest_id,
        title=title,
        depends_on=depends_on,
        state=state,
        rewards={"xp": xp, "items": items},
    ), 200


@bp.post("/v1/play/campaigns/<campaign_id>/quests/<quest_id>/rewards/award")
@require_auth
def award_play_campaign_quest_rewards(username, _role, campaign_id, quest_id):
    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        if campaign["owner"] != username:
            return jsonify(error="forbidden"), 403

        quest = conn.execute(
            "SELECT id, quest_id, state FROM play_quests "
            "WHERE campaign_id = ? AND quest_id = ?",
            (campaign_id, quest_id),
        ).fetchone()
        if quest is None:
            return jsonify(error="quest not found"), 404

        reward = conn.execute(
            "SELECT xp, items_json, awarded FROM play_quest_rewards "
            "WHERE campaign_id = ? AND quest_id = ?",
            (campaign_id, quest_id),
        ).fetchone()

        if quest["state"] != "completed" or reward is None:
            return jsonify(error="rewards not available"), 409
        if reward["awarded"]:
            return jsonify(error="rewards already awarded"), 409

        xp = reward["xp"]
        items = json.loads(reward["items_json"])

        members = conn.execute(
            "SELECT character_id FROM play_members WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchall()

        for member in members:
            conn.execute(
                "INSERT INTO play_character_quest_rewards "
                "(campaign_id, character_id, quest_id, xp, items_json) "
                "VALUES (?, ?, ?, ?, ?)",
                (campaign_id, member["character_id"], quest_id, xp, json.dumps(items)),
            )
            for item_id, quantity in items.items():
                existing_item = conn.execute(
                    "SELECT quantity FROM play_character_inventory "
                    "WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
                    (campaign_id, member["character_id"], item_id),
                ).fetchone()
                new_item_quantity = (
                    existing_item["quantity"] if existing_item is not None else 0
                ) + quantity
                conn.execute(
                    "INSERT INTO play_character_inventory "
                    "(campaign_id, character_id, item_id, quantity) "
                    "VALUES (?, ?, ?, ?) "
                    "ON CONFLICT (campaign_id, character_id, item_id) "
                    "DO UPDATE SET quantity = excluded.quantity",
                    (campaign_id, member["character_id"], item_id, new_item_quantity),
                )

        conn.execute(
            "UPDATE play_quest_rewards SET awarded = 1 "
            "WHERE campaign_id = ? AND quest_id = ?",
            (campaign_id, quest_id),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify(quest_id=quest_id, awarded=True, xp=xp, items=items), 201


@bp.get("/v1/play/campaigns/<campaign_id>/characters/<char_id>/rewards")
@require_auth
def get_play_campaign_character_rewards(username, _role, campaign_id, char_id):
    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        membership_error = _require_campaign_member(conn, campaign, username)
        if membership_error is not None:
            return membership_error

        owner_record = conn.execute(
            "SELECT 1 FROM play_character_owners "
            "WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, char_id),
        ).fetchone()
        if owner_record is None:
            return jsonify(error="character not found"), 404

        rows = conn.execute(
            "SELECT xp, items_json FROM play_character_quest_rewards "
            "WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, char_id),
        ).fetchall()
    finally:
        conn.close()

    total_xp = 0
    total_items = {}
    for row in rows:
        total_xp += row["xp"]
        for item_id, quantity in json.loads(row["items_json"]).items():
            total_items[item_id] = total_items.get(item_id, 0) + quantity

    return jsonify(character_id=char_id, xp=total_xp, items=total_items), 200


def _serialize_world_event(row):
    event = dict(
        event_id=row["event_id"],
        turn_number=row["turn_number"],
        title=row["title"],
        text=row["text"],
        status=row["status"],
    )
    if row["status"] == "resolved":
        event["resolution"] = {
            "turn_number": row["resolution_turn_number"],
            "text": row["resolution_text"],
        }
    return event


@bp.post("/v1/play/campaigns/<campaign_id>/world-events")
@require_auth
def create_play_campaign_world_event(username, _role, campaign_id):
    data = request.get_json(silent=True) or {}
    event_id = data.get("event_id")
    turn_number = data.get("turn_number")
    title = data.get("title")
    text = data.get("text")

    if not valid_nonempty_str(event_id) or not valid_nonempty_str(title) or not valid_nonempty_str(text):
        return jsonify(error="invalid body"), 400
    if not valid_int(turn_number):
        return jsonify(error="invalid body"), 400

    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner, turn_number FROM play_campaigns WHERE id = ?",
            (campaign_id,),
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        if campaign["owner"] != username:
            return jsonify(error="forbidden"), 403

        if turn_number < campaign["turn_number"]:
            return jsonify(error="invalid turn_number"), 400

        existing = conn.execute(
            "SELECT 1 FROM play_world_events WHERE campaign_id = ? AND event_id = ?",
            (campaign_id, event_id),
        ).fetchone()
        if existing is not None:
            return jsonify(error="event already exists"), 409

        conn.execute(
            "INSERT INTO play_world_events "
            "(campaign_id, event_id, turn_number, title, text, status) "
            "VALUES (?, ?, ?, ?, ?, 'scheduled')",
            (campaign_id, event_id, turn_number, title, text),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify(
        event_id=event_id,
        turn_number=turn_number,
        title=title,
        text=text,
        status="scheduled",
    ), 201


@bp.post("/v1/play/campaigns/<campaign_id>/world-events/<event_id>/resolve")
@require_auth
def resolve_play_campaign_world_event(username, _role, campaign_id, event_id):
    data = request.get_json(silent=True) or {}
    resolution_text = data.get("text")

    if not valid_nonempty_str(resolution_text):
        return jsonify(error="invalid body"), 400

    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner, turn_number FROM play_campaigns WHERE id = ?",
            (campaign_id,),
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        if campaign["owner"] != username:
            return jsonify(error="forbidden"), 403

        event = conn.execute(
            "SELECT * FROM play_world_events WHERE campaign_id = ? AND event_id = ?",
            (campaign_id, event_id),
        ).fetchone()
        if event is None:
            return jsonify(error="event not found"), 404

        if event["status"] == "resolved":
            return jsonify(error="event already resolved"), 409

        if campaign["turn_number"] != event["turn_number"]:
            return jsonify(error="turn number mismatch"), 409

        conn.execute(
            "UPDATE play_world_events SET status = 'resolved', "
            "resolution_turn_number = ?, resolution_text = ? "
            "WHERE campaign_id = ? AND event_id = ?",
            (event["turn_number"], resolution_text, campaign_id, event_id),
        )
        conn.commit()

        title = event["title"]
        text = event["text"]
        turn_number = event["turn_number"]
    finally:
        conn.close()

    return jsonify(
        event_id=event_id,
        turn_number=turn_number,
        title=title,
        text=text,
        status="resolved",
        resolution={"turn_number": turn_number, "text": resolution_text},
    ), 201


@bp.get("/v1/play/campaigns/<campaign_id>/world-events")
@require_auth
def get_play_campaign_world_events(username, _role, campaign_id):
    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        membership_error = _require_campaign_member(conn, campaign, username)
        if membership_error is not None:
            return membership_error

        rows = conn.execute(
            "SELECT * FROM play_world_events WHERE campaign_id = ? "
            "ORDER BY turn_number ASC, id ASC",
            (campaign_id,),
        ).fetchall()
    finally:
        conn.close()

    return jsonify(events=[_serialize_world_event(row) for row in rows]), 200


_SEASON_OFFSETS = {"spring": 0, "summer": 1, "autumn": 2, "winter": 3}
_WEATHER_BY_OFFSET = {0: "clear", 1: "rain", 2: "wind", 3: "snow"}


def _calendar_weather(day, season):
    return _WEATHER_BY_OFFSET[(day + _SEASON_OFFSETS[season]) % 4]


def _serialize_calendar(row):
    return dict(
        day=row["day"],
        season=row["season"],
        weather=_calendar_weather(row["day"], row["season"]),
    )


@bp.post("/v1/play/campaigns/<campaign_id>/calendar")
@require_auth
def create_play_campaign_calendar(username, _role, campaign_id):
    data = request.get_json(silent=True) or {}
    day = data.get("day")
    season = data.get("season")

    if not valid_int(day) or day < 1:
        return jsonify(error="invalid body"), 400
    if season not in _SEASON_OFFSETS:
        return jsonify(error="invalid body"), 400

    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        if campaign["owner"] != username:
            return jsonify(error="forbidden"), 403

        existing = conn.execute(
            "SELECT 1 FROM play_calendar WHERE campaign_id = ?", (campaign_id,)
        ).fetchone()
        if existing is not None:
            return jsonify(error="calendar already initialized"), 409

        conn.execute(
            "INSERT INTO play_calendar (campaign_id, day, season) VALUES (?, ?, ?)",
            (campaign_id, day, season),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify(
        day=day, season=season, weather=_calendar_weather(day, season)
    ), 201


@bp.get("/v1/play/campaigns/<campaign_id>/calendar")
@require_auth
def get_play_campaign_calendar(username, _role, campaign_id):
    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        membership_error = _require_campaign_member(conn, campaign, username)
        if membership_error is not None:
            return membership_error

        row = conn.execute(
            "SELECT day, season FROM play_calendar WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
        if row is None:
            return jsonify(error="calendar not initialized"), 404
    finally:
        conn.close()

    return jsonify(_serialize_calendar(row)), 200


@bp.post("/v1/play/campaigns/<campaign_id>/calendar/advance")
@require_auth
def advance_play_campaign_calendar(username, _role, campaign_id):
    data = request.get_json(silent=True) or {}
    days = data.get("days")

    if not valid_int_in_range(days, 1, 30):
        return jsonify(error="invalid body"), 400

    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        if campaign["owner"] != username:
            return jsonify(error="forbidden"), 403

        row = conn.execute(
            "SELECT day, season FROM play_calendar WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
        if row is None:
            return jsonify(error="calendar not initialized"), 404

        new_day = row["day"] + days
        conn.execute(
            "UPDATE play_calendar SET day = ? WHERE campaign_id = ?",
            (new_day, campaign_id),
        )
        conn.commit()
        season = row["season"]
    finally:
        conn.close()

    return jsonify(
        day=new_day, season=season, weather=_calendar_weather(new_day, season)
    ), 200


VALID_SETTLEMENT_AVAILABILITY = frozenset({"open", "limited", "closed"})


def _normalized_services(services):
    """Trimmed, uniqueness-checked service list, or None if invalid."""
    if not isinstance(services, list) or not services:
        return None

    normalized = []
    seen = set()
    for service in services:
        if not isinstance(service, str):
            return None
        trimmed = service.strip()
        if not trimmed or trimmed in seen:
            return None
        seen.add(trimmed)
        normalized.append(trimmed)
    return normalized


def _settlement_discoverers(conn, campaign_id, settlement_id):
    rows = conn.execute(
        "SELECT character_id FROM play_settlement_discoveries "
        "WHERE campaign_id = ? AND settlement_id = ? ORDER BY id ASC",
        (campaign_id, settlement_id),
    ).fetchall()
    return [row["character_id"] for row in rows]


def _serialize_settlement(row, discovered_by):
    return {
        "settlement_id": row["settlement_id"],
        "name": row["name"],
        "services": json.loads(row["services_json"]),
        "availability": row["availability"],
        "discovered_by": discovered_by,
    }


@bp.post("/v1/play/campaigns/<campaign_id>/settlements")
@require_auth
def create_play_campaign_settlement(username, _role, campaign_id):
    data = request.get_json(silent=True) or {}
    settlement_id = data.get("settlement_id")
    name = data.get("name")
    services = _normalized_services(data.get("services"))
    availability = data.get("availability")

    if not valid_nonempty_str(settlement_id):
        return jsonify(error="invalid settlement_id"), 400
    if not valid_nonempty_str(name):
        return jsonify(error="invalid name"), 400
    if services is None:
        return jsonify(error="invalid services"), 400
    if availability not in VALID_SETTLEMENT_AVAILABILITY:
        return jsonify(error="invalid availability"), 400

    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        if campaign["owner"] != username:
            return jsonify(error="forbidden"), 403

        existing = conn.execute(
            "SELECT id FROM play_settlements WHERE campaign_id = ? AND settlement_id = ?",
            (campaign_id, settlement_id),
        ).fetchone()
        if existing is not None:
            return jsonify(error="settlement already exists"), 409

        conn.execute(
            "INSERT INTO play_settlements "
            "(campaign_id, settlement_id, name, services_json, availability) "
            "VALUES (?, ?, ?, ?, ?)",
            (campaign_id, settlement_id, name, json.dumps(services), availability),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify(
        settlement_id=settlement_id,
        name=name,
        services=services,
        availability=availability,
        discovered_by=[],
    ), 201


@bp.put("/v1/play/campaigns/<campaign_id>/settlements/<settlement_id>")
@require_auth
def update_play_campaign_settlement(username, _role, campaign_id, settlement_id):
    data = request.get_json(silent=True) or {}
    name = data.get("name")
    services = _normalized_services(data.get("services"))
    availability = data.get("availability")

    if not valid_nonempty_str(name):
        return jsonify(error="invalid name"), 400
    if services is None:
        return jsonify(error="invalid services"), 400
    if availability not in VALID_SETTLEMENT_AVAILABILITY:
        return jsonify(error="invalid availability"), 400

    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        if campaign["owner"] != username:
            return jsonify(error="forbidden"), 403

        settlement = conn.execute(
            "SELECT id FROM play_settlements WHERE campaign_id = ? AND settlement_id = ?",
            (campaign_id, settlement_id),
        ).fetchone()
        if settlement is None:
            return jsonify(error="settlement not found"), 404

        conn.execute(
            "UPDATE play_settlements SET name = ?, services_json = ?, availability = ? "
            "WHERE campaign_id = ? AND settlement_id = ?",
            (name, json.dumps(services), availability, campaign_id, settlement_id),
        )
        conn.commit()

        discovered_by = _settlement_discoverers(conn, campaign_id, settlement_id)
    finally:
        conn.close()

    return jsonify(
        settlement_id=settlement_id,
        name=name,
        services=services,
        availability=availability,
        discovered_by=discovered_by,
    ), 200


@bp.post("/v1/play/campaigns/<campaign_id>/settlements/<settlement_id>/discover")
@require_auth
def discover_play_campaign_settlement(username, role, campaign_id, settlement_id):
    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        if role != "player":
            return jsonify(error="forbidden"), 403

        member = conn.execute(
            "SELECT character_id FROM play_members WHERE campaign_id = ? AND username = ?",
            (campaign_id, username),
        ).fetchone()
        if member is None:
            return jsonify(error="not a campaign member"), 403

        character_id = member["character_id"]

        settlement = conn.execute(
            "SELECT settlement_id, name, services_json, availability "
            "FROM play_settlements WHERE campaign_id = ? AND settlement_id = ?",
            (campaign_id, settlement_id),
        ).fetchone()
        if settlement is None:
            return jsonify(error="settlement not found"), 404

        existing = conn.execute(
            "SELECT id FROM play_settlement_discoveries "
            "WHERE campaign_id = ? AND settlement_id = ? AND character_id = ?",
            (campaign_id, settlement_id, character_id),
        ).fetchone()

        if existing is not None:
            return jsonify(
                _serialize_settlement(settlement, [character_id])
            ), 200

        conn.execute(
            "INSERT INTO play_settlement_discoveries "
            "(campaign_id, settlement_id, character_id) VALUES (?, ?, ?)",
            (campaign_id, settlement_id, character_id),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify(_serialize_settlement(settlement, [character_id])), 201


@bp.get("/v1/play/campaigns/<campaign_id>/settlements")
@require_auth
def get_play_campaign_settlements(username, _role, campaign_id):
    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        membership_error = _require_campaign_member(conn, campaign, username)
        if membership_error is not None:
            return membership_error

        is_dm = campaign["owner"] == username
        own_character_id = None
        if not is_dm:
            member = conn.execute(
                "SELECT character_id FROM play_members "
                "WHERE campaign_id = ? AND username = ?",
                (campaign_id, username),
            ).fetchone()
            own_character_id = member["character_id"] if member else None

        settlements = conn.execute(
            "SELECT settlement_id, name, services_json, availability "
            "FROM play_settlements WHERE campaign_id = ? ORDER BY id ASC",
            (campaign_id,),
        ).fetchall()

        result = []
        for settlement in settlements:
            discovered_by = _settlement_discoverers(
                conn, campaign_id, settlement["settlement_id"]
            )
            if is_dm:
                result.append(_serialize_settlement(settlement, discovered_by))
            elif own_character_id in discovered_by:
                result.append(
                    _serialize_settlement(settlement, [own_character_id])
                )
    finally:
        conn.close()

    return jsonify(settlements=result), 200


def _valid_shop_stock(stock):
    """Normalized {item_id: positive_qty} dict, or None if invalid."""
    if not isinstance(stock, dict) or not stock:
        return None

    normalized = {}
    for item_id, quantity in stock.items():
        if item_id not in VALID_INVENTORY_ITEM_IDS:
            return None
        if not valid_int(quantity) or quantity <= 0:
            return None
        normalized[item_id] = quantity
    return normalized


def _serialize_shop(row):
    return {
        "shop_id": row["shop_id"],
        "name": row["name"],
        "stock": json.loads(row["stock_json"]),
        "buy_price": row["buy_price"],
        "sell_price": row["sell_price"],
    }


@bp.post("/v1/play/campaigns/<campaign_id>/settlements/<settlement_id>/shops")
@require_auth
def create_play_campaign_settlement_shop(username, _role, campaign_id, settlement_id):
    data = request.get_json(silent=True) or {}
    shop_id = data.get("shop_id")
    name = data.get("name")
    stock = _valid_shop_stock(data.get("stock"))
    buy_price = data.get("buy_price")
    sell_price = data.get("sell_price")

    if not valid_nonempty_str(shop_id):
        return jsonify(error="invalid shop_id"), 400
    if not valid_nonempty_str(name):
        return jsonify(error="invalid name"), 400
    if stock is None:
        return jsonify(error="invalid stock"), 400
    if not valid_int(buy_price) or buy_price <= 0:
        return jsonify(error="invalid buy_price"), 400
    if not valid_int(sell_price) or sell_price < 0:
        return jsonify(error="invalid sell_price"), 400

    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        if campaign["owner"] != username:
            return jsonify(error="forbidden"), 403

        settlement = conn.execute(
            "SELECT id FROM play_settlements WHERE campaign_id = ? AND settlement_id = ?",
            (campaign_id, settlement_id),
        ).fetchone()
        if settlement is None:
            return jsonify(error="settlement not found"), 404

        existing = conn.execute(
            "SELECT id FROM play_shops "
            "WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ?",
            (campaign_id, settlement_id, shop_id),
        ).fetchone()
        if existing is not None:
            return jsonify(error="shop already exists"), 409

        conn.execute(
            "INSERT INTO play_shops "
            "(campaign_id, settlement_id, shop_id, name, stock_json, buy_price, sell_price) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                campaign_id,
                settlement_id,
                shop_id,
                name,
                json.dumps(stock),
                buy_price,
                sell_price,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify(
        shop_id=shop_id,
        name=name,
        stock=stock,
        buy_price=buy_price,
        sell_price=sell_price,
    ), 201


@bp.get("/v1/play/campaigns/<campaign_id>/settlements/<settlement_id>/shops/<shop_id>")
@require_auth
def get_play_campaign_settlement_shop(username, _role, campaign_id, settlement_id, shop_id):
    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        membership_error = _require_campaign_member(conn, campaign, username)
        if membership_error is not None:
            return membership_error

        shop = conn.execute(
            "SELECT shop_id, name, stock_json, buy_price, sell_price FROM play_shops "
            "WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ?",
            (campaign_id, settlement_id, shop_id),
        ).fetchone()
        if shop is None:
            return jsonify(error="shop not found"), 404

        is_dm = campaign["owner"] == username
        if not is_dm:
            member = conn.execute(
                "SELECT character_id FROM play_members "
                "WHERE campaign_id = ? AND username = ?",
                (campaign_id, username),
            ).fetchone()
            own_character_id = member["character_id"] if member else None
            discovered_by = _settlement_discoverers(conn, campaign_id, settlement_id)
            if own_character_id not in discovered_by:
                return jsonify(error="shop not found"), 404
    finally:
        conn.close()

    return jsonify(_serialize_shop(shop)), 200


def _shop_transaction_actors(conn, campaign_id, settlement_id, shop_id, character_id):
    """(campaign, shop, owner_record) tuple, or a (body, status) error tuple."""
    campaign = conn.execute(
        "SELECT id, owner FROM play_campaigns WHERE id = ?", (campaign_id,)
    ).fetchone()
    if campaign is None:
        return jsonify(error="campaign not found"), 404

    settlement = conn.execute(
        "SELECT id FROM play_settlements WHERE campaign_id = ? AND settlement_id = ?",
        (campaign_id, settlement_id),
    ).fetchone()
    if settlement is None:
        return jsonify(error="settlement not found"), 404

    shop = conn.execute(
        "SELECT stock_json, buy_price, sell_price FROM play_shops "
        "WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ?",
        (campaign_id, settlement_id, shop_id),
    ).fetchone()
    if shop is None:
        return jsonify(error="shop not found"), 404

    owner_record = conn.execute(
        "SELECT owner FROM play_character_owners "
        "WHERE campaign_id = ? AND character_id = ?",
        (campaign_id, character_id),
    ).fetchone()
    if owner_record is None:
        return jsonify(error="character not found"), 404

    return campaign, shop, owner_record


@bp.post(
    "/v1/play/campaigns/<campaign_id>/settlements/<settlement_id>/shops/<shop_id>/buy"
)
@require_auth
def buy_play_campaign_settlement_shop_item(
    username, role, campaign_id, settlement_id, shop_id
):
    data = request.get_json(silent=True) or {}
    character_id = data.get("character_id")
    item_id = data.get("item_id")
    quantity = data.get("quantity")

    if not valid_nonempty_str(character_id):
        return jsonify(error="invalid character_id"), 400
    if item_id not in VALID_INVENTORY_ITEM_IDS:
        return jsonify(error="invalid item_id"), 400
    if not valid_int(quantity) or quantity <= 0:
        return jsonify(error="invalid quantity"), 400

    conn = get_db()
    try:
        actors = _shop_transaction_actors(
            conn, campaign_id, settlement_id, shop_id, character_id
        )
        if len(actors) == 2:
            return actors
        _campaign, shop, owner_record = actors

        if role != "player" or owner_record["owner"] != username:
            return jsonify(error="forbidden"), 403

        stock = json.loads(shop["stock_json"])
        current_stock = stock.get(item_id, 0)
        if current_stock < quantity:
            return jsonify(error="insufficient stock"), 409

        cost = shop["buy_price"] * quantity
        currency = conn.execute(
            "SELECT gold FROM play_character_currency "
            "WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, character_id),
        ).fetchone()
        current_gold = currency["gold"] if currency is not None else 0
        if current_gold < cost:
            return jsonify(error="insufficient gold"), 409

        new_stock = current_stock - quantity
        stock[item_id] = new_stock
        new_gold = current_gold - cost

        existing_item = conn.execute(
            "SELECT quantity FROM play_character_inventory "
            "WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
            (campaign_id, character_id, item_id),
        ).fetchone()
        new_item_quantity = (
            existing_item["quantity"] if existing_item is not None else 0
        ) + quantity

        conn.execute(
            "UPDATE play_shops SET stock_json = ? "
            "WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ?",
            (json.dumps(stock), campaign_id, settlement_id, shop_id),
        )
        conn.execute(
            "INSERT INTO play_character_currency (campaign_id, character_id, gold) "
            "VALUES (?, ?, ?) "
            "ON CONFLICT (campaign_id, character_id) "
            "DO UPDATE SET gold = excluded.gold",
            (campaign_id, character_id, new_gold),
        )
        conn.execute(
            "INSERT INTO play_character_inventory "
            "(campaign_id, character_id, item_id, quantity) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT (campaign_id, character_id, item_id) "
            "DO UPDATE SET quantity = excluded.quantity",
            (campaign_id, character_id, item_id, new_item_quantity),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify(
        character_id=character_id,
        item_id=item_id,
        quantity=quantity,
        gold=new_gold,
        stock=new_stock,
    ), 200


@bp.post(
    "/v1/play/campaigns/<campaign_id>/settlements/<settlement_id>/shops/<shop_id>/sell"
)
@require_auth
def sell_play_campaign_settlement_shop_item(
    username, role, campaign_id, settlement_id, shop_id
):
    data = request.get_json(silent=True) or {}
    character_id = data.get("character_id")
    item_id = data.get("item_id")
    quantity = data.get("quantity")

    if not valid_nonempty_str(character_id):
        return jsonify(error="invalid character_id"), 400
    if item_id not in VALID_INVENTORY_ITEM_IDS:
        return jsonify(error="invalid item_id"), 400
    if not valid_int(quantity) or quantity <= 0:
        return jsonify(error="invalid quantity"), 400

    conn = get_db()
    try:
        actors = _shop_transaction_actors(
            conn, campaign_id, settlement_id, shop_id, character_id
        )
        if len(actors) == 2:
            return actors
        _campaign, shop, owner_record = actors

        if role != "player" or owner_record["owner"] != username:
            return jsonify(error="forbidden"), 403

        existing_item = conn.execute(
            "SELECT quantity FROM play_character_inventory "
            "WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
            (campaign_id, character_id, item_id),
        ).fetchone()
        held_quantity = existing_item["quantity"] if existing_item is not None else 0
        if held_quantity < quantity:
            return jsonify(error="insufficient inventory"), 409

        currency = conn.execute(
            "SELECT gold FROM play_character_currency "
            "WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, character_id),
        ).fetchone()
        current_gold = currency["gold"] if currency is not None else 0

        stock = json.loads(shop["stock_json"])
        new_stock = stock.get(item_id, 0) + quantity
        stock[item_id] = new_stock

        new_item_quantity = held_quantity - quantity
        new_gold = current_gold + shop["sell_price"] * quantity

        conn.execute(
            "UPDATE play_shops SET stock_json = ? "
            "WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ?",
            (json.dumps(stock), campaign_id, settlement_id, shop_id),
        )
        conn.execute(
            "INSERT INTO play_character_inventory "
            "(campaign_id, character_id, item_id, quantity) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT (campaign_id, character_id, item_id) "
            "DO UPDATE SET quantity = excluded.quantity",
            (campaign_id, character_id, item_id, new_item_quantity),
        )
        conn.execute(
            "INSERT INTO play_character_currency (campaign_id, character_id, gold) "
            "VALUES (?, ?, ?) "
            "ON CONFLICT (campaign_id, character_id) "
            "DO UPDATE SET gold = excluded.gold",
            (campaign_id, character_id, new_gold),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify(
        character_id=character_id,
        item_id=item_id,
        quantity=quantity,
        gold=new_gold,
        stock=new_stock,
    ), 200


def _valid_recipe_ingredients(ingredients):
    """Normalized {item_id: positive_qty} dict, or None if invalid."""
    if not isinstance(ingredients, dict) or not ingredients:
        return None

    normalized = {}
    for item_id, quantity in ingredients.items():
        if item_id not in VALID_INVENTORY_ITEM_IDS:
            return None
        if not valid_int(quantity) or quantity <= 0:
            return None
        normalized[item_id] = quantity
    return normalized


def _serialize_recipe(row):
    return {
        "recipe_id": row["recipe_id"],
        "name": row["name"],
        "ingredients": json.loads(row["ingredients_json"]),
        "output_item": row["output_item"],
        "output_quantity": row["output_quantity"],
    }


@bp.post("/v1/play/campaigns/<campaign_id>/recipes")
@require_auth
def create_play_campaign_recipe(username, _role, campaign_id):
    data = request.get_json(silent=True) or {}
    recipe_id = data.get("recipe_id")
    name = data.get("name")
    ingredients = _valid_recipe_ingredients(data.get("ingredients"))
    output_item = data.get("output_item")
    output_quantity = data.get("output_quantity")

    if not valid_nonempty_str(recipe_id):
        return jsonify(error="invalid recipe_id"), 400
    if not valid_nonempty_str(name):
        return jsonify(error="invalid name"), 400
    if ingredients is None:
        return jsonify(error="invalid ingredients"), 400
    if output_item not in VALID_INVENTORY_ITEM_IDS:
        return jsonify(error="invalid output_item"), 400
    if not valid_int(output_quantity) or output_quantity <= 0:
        return jsonify(error="invalid output_quantity"), 400

    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        if campaign["owner"] != username:
            return jsonify(error="forbidden"), 403

        existing = conn.execute(
            "SELECT id FROM play_recipes WHERE campaign_id = ? AND recipe_id = ?",
            (campaign_id, recipe_id),
        ).fetchone()
        if existing is not None:
            return jsonify(error="recipe already exists"), 409

        conn.execute(
            "INSERT INTO play_recipes "
            "(campaign_id, recipe_id, name, ingredients_json, output_item, output_quantity) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                campaign_id,
                recipe_id,
                name,
                json.dumps(ingredients),
                output_item,
                output_quantity,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify(
        recipe_id=recipe_id,
        name=name,
        ingredients=ingredients,
        output_item=output_item,
        output_quantity=output_quantity,
    ), 201


@bp.get("/v1/play/campaigns/<campaign_id>/recipes")
@require_auth
def list_play_campaign_recipes(username, _role, campaign_id):
    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        membership_error = _require_campaign_member(conn, campaign, username)
        if membership_error is not None:
            return membership_error

        rows = conn.execute(
            "SELECT recipe_id, name, ingredients_json, output_item, output_quantity "
            "FROM play_recipes WHERE campaign_id = ? ORDER BY id ASC",
            (campaign_id,),
        ).fetchall()
        recipes = [_serialize_recipe(row) for row in rows]
    finally:
        conn.close()

    return jsonify(recipes=recipes), 200


@bp.post("/v1/play/campaigns/<campaign_id>/recipes/<recipe_id>/craft")
@require_auth
def craft_play_campaign_recipe(username, role, campaign_id, recipe_id):
    data = request.get_json(silent=True) or {}
    character_id = data.get("character_id")

    if not valid_nonempty_str(character_id):
        return jsonify(error="invalid character_id"), 400

    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        recipe = conn.execute(
            "SELECT recipe_id, ingredients_json, output_item, output_quantity "
            "FROM play_recipes WHERE campaign_id = ? AND recipe_id = ?",
            (campaign_id, recipe_id),
        ).fetchone()
        if recipe is None:
            return jsonify(error="recipe not found"), 404

        owner_record = conn.execute(
            "SELECT owner FROM play_character_owners "
            "WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, character_id),
        ).fetchone()
        if owner_record is None:
            return jsonify(error="character not found"), 404

        if role != "player" or owner_record["owner"] != username:
            return jsonify(error="forbidden"), 403

        ingredients = json.loads(recipe["ingredients_json"])
        held_quantities = {}
        for item_id, required_quantity in ingredients.items():
            existing_item = conn.execute(
                "SELECT quantity FROM play_character_inventory "
                "WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
                (campaign_id, character_id, item_id),
            ).fetchone()
            held_quantity = existing_item["quantity"] if existing_item is not None else 0
            if held_quantity < required_quantity:
                return jsonify(error="insufficient ingredients"), 409
            held_quantities[item_id] = held_quantity

        output_item = recipe["output_item"]
        output_quantity = recipe["output_quantity"]

        for item_id, required_quantity in ingredients.items():
            new_quantity = held_quantities[item_id] - required_quantity
            conn.execute(
                "INSERT INTO play_character_inventory "
                "(campaign_id, character_id, item_id, quantity) "
                "VALUES (?, ?, ?, ?) "
                "ON CONFLICT (campaign_id, character_id, item_id) "
                "DO UPDATE SET quantity = excluded.quantity",
                (campaign_id, character_id, item_id, new_quantity),
            )

        existing_output = conn.execute(
            "SELECT quantity FROM play_character_inventory "
            "WHERE campaign_id = ? AND character_id = ? AND item_id = ?",
            (campaign_id, character_id, output_item),
        ).fetchone()
        current_output_quantity = (
            existing_output["quantity"] if existing_output is not None else 0
        )
        new_output_quantity = current_output_quantity + output_quantity

        conn.execute(
            "INSERT INTO play_character_inventory "
            "(campaign_id, character_id, item_id, quantity) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT (campaign_id, character_id, item_id) "
            "DO UPDATE SET quantity = excluded.quantity",
            (campaign_id, character_id, output_item, new_output_quantity),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify(
        character_id=character_id,
        recipe_id=recipe_id,
        output_item=output_item,
        output_quantity=output_quantity,
    ), 201


@bp.post("/v1/play/campaigns/<campaign_id>/downtime/activities")
@require_auth
def create_play_campaign_downtime_activity(username, _role, campaign_id):
    data = request.get_json(silent=True) or {}
    activity_id = data.get("activity_id")
    name = data.get("name")
    cycles_required = data.get("cycles_required")

    if not valid_nonempty_str(activity_id):
        return jsonify(error="invalid activity_id"), 400
    if not valid_nonempty_str(name):
        return jsonify(error="invalid name"), 400
    if not valid_int_in_range(cycles_required, 1, 10):
        return jsonify(error="invalid cycles_required"), 400

    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        if campaign["owner"] != username:
            return jsonify(error="forbidden"), 403

        existing = conn.execute(
            "SELECT id FROM play_downtime_activities "
            "WHERE campaign_id = ? AND activity_id = ?",
            (campaign_id, activity_id),
        ).fetchone()
        if existing is not None:
            return jsonify(error="activity already exists"), 409

        conn.execute(
            "INSERT INTO play_downtime_activities "
            "(campaign_id, activity_id, name, cycles_required) "
            "VALUES (?, ?, ?, ?)",
            (campaign_id, activity_id, name, cycles_required),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify(
        activity_id=activity_id,
        name=name,
        cycles_required=cycles_required,
    ), 201


@bp.post(
    "/v1/play/campaigns/<campaign_id>/characters/<character_id>/downtime/allocations"
)
@require_auth
def create_play_campaign_downtime_allocation(username, role, campaign_id, character_id):
    data = request.get_json(silent=True) or {}
    activity_id = data.get("activity_id")

    if not valid_nonempty_str(activity_id):
        return jsonify(error="invalid activity_id"), 400

    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        owner_record = conn.execute(
            "SELECT owner FROM play_character_owners "
            "WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, character_id),
        ).fetchone()
        if owner_record is None:
            return jsonify(error="character not found"), 404

        if role != "player" or owner_record["owner"] != username:
            return jsonify(error="forbidden"), 403

        activity = conn.execute(
            "SELECT activity_id FROM play_downtime_activities "
            "WHERE campaign_id = ? AND activity_id = ?",
            (campaign_id, activity_id),
        ).fetchone()
        if activity is None:
            return jsonify(error="activity not found"), 404

        existing = conn.execute(
            "SELECT id FROM play_downtime_allocations "
            "WHERE campaign_id = ? AND character_id = ? AND activity_id = ?",
            (campaign_id, character_id, activity_id),
        ).fetchone()
        if existing is not None:
            return jsonify(error="allocation already exists"), 409

        conn.execute(
            "INSERT INTO play_downtime_allocations "
            "(campaign_id, character_id, activity_id, cycles_completed, completions) "
            "VALUES (?, ?, ?, 0, 0)",
            (campaign_id, character_id, activity_id),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify(
        character_id=character_id,
        activity_id=activity_id,
        cycles_completed=0,
        completions=0,
    ), 201


@bp.post(
    "/v1/play/campaigns/<campaign_id>/characters/<character_id>"
    "/downtime/allocations/<activity_id>/progress"
)
@require_auth
def progress_play_campaign_downtime_allocation(
    username, role, campaign_id, character_id, activity_id
):
    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        owner_record = conn.execute(
            "SELECT owner FROM play_character_owners "
            "WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, character_id),
        ).fetchone()
        if owner_record is None:
            return jsonify(error="character not found"), 404

        if role != "player" or owner_record["owner"] != username:
            return jsonify(error="forbidden"), 403

        activity = conn.execute(
            "SELECT activity_id, cycles_required FROM play_downtime_activities "
            "WHERE campaign_id = ? AND activity_id = ?",
            (campaign_id, activity_id),
        ).fetchone()
        if activity is None:
            return jsonify(error="activity not found"), 404

        allocation = conn.execute(
            "SELECT cycles_completed, completions FROM play_downtime_allocations "
            "WHERE campaign_id = ? AND character_id = ? AND activity_id = ?",
            (campaign_id, character_id, activity_id),
        ).fetchone()
        if allocation is None:
            return jsonify(error="allocation not found"), 404

        cycles_completed = allocation["cycles_completed"] + 1
        completions = allocation["completions"]
        if cycles_completed >= activity["cycles_required"]:
            cycles_completed = 0
            completions += 1

        conn.execute(
            "UPDATE play_downtime_allocations "
            "SET cycles_completed = ?, completions = ? "
            "WHERE campaign_id = ? AND character_id = ? AND activity_id = ?",
            (cycles_completed, completions, campaign_id, character_id, activity_id),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify(
        character_id=character_id,
        activity_id=activity_id,
        cycles_completed=cycles_completed,
        completions=completions,
    ), 200


@bp.get(
    "/v1/play/campaigns/<campaign_id>/characters/<character_id>"
    "/downtime/allocations/<activity_id>"
)
@require_auth
def get_play_campaign_downtime_allocation(username, _role, campaign_id, character_id, activity_id):
    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        membership_error = _require_campaign_member(conn, campaign, username)
        if membership_error is not None:
            return membership_error

        character = conn.execute(
            "SELECT owner FROM play_character_owners "
            "WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, character_id),
        ).fetchone()
        if character is None:
            return jsonify(error="character not found"), 404

        activity = conn.execute(
            "SELECT activity_id FROM play_downtime_activities "
            "WHERE campaign_id = ? AND activity_id = ?",
            (campaign_id, activity_id),
        ).fetchone()
        if activity is None:
            return jsonify(error="activity not found"), 404

        allocation = conn.execute(
            "SELECT cycles_completed, completions FROM play_downtime_allocations "
            "WHERE campaign_id = ? AND character_id = ? AND activity_id = ?",
            (campaign_id, character_id, activity_id),
        ).fetchone()
        if allocation is None:
            return jsonify(error="allocation not found"), 404
    finally:
        conn.close()

    return jsonify(
        character_id=character_id,
        activity_id=activity_id,
        cycles_completed=allocation["cycles_completed"],
        completions=allocation["completions"],
    ), 200


def _valid_consent(value):
    if not isinstance(value, list) or not value:
        return False
    seen = set()
    for entry in value:
        if not isinstance(entry, str) or not entry.strip() or entry in seen:
            return False
        seen.add(entry)
    return True


@bp.put("/v1/play/campaigns/<campaign_id>/session-zero")
@require_auth
def put_play_campaign_session_zero(username, _role, campaign_id):
    data = request.get_json(silent=True) or {}
    rules = data.get("rules")
    tone = data.get("tone")
    consent = data.get("consent")

    if not valid_nonempty_str(rules):
        return jsonify(error="invalid rules"), 400
    if not valid_nonempty_str(tone):
        return jsonify(error="invalid tone"), 400
    if not _valid_consent(consent):
        return jsonify(error="invalid consent"), 400

    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner, status FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        if campaign["owner"] != username:
            return jsonify(error="forbidden"), 403

        if campaign["status"] != "lobby":
            return jsonify(error="cannot update session-zero"), 409

        conn.execute(
            "INSERT INTO play_session_zero (campaign_id, rules, tone, consent_json) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(campaign_id) DO UPDATE SET "
            "rules = excluded.rules, tone = excluded.tone, consent_json = excluded.consent_json",
            (campaign_id, rules, tone, json.dumps(consent)),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify(rules=rules, tone=tone, consent=consent), 200


@bp.get("/v1/play/campaigns/<campaign_id>/session-zero")
@require_auth
def get_play_campaign_session_zero(username, _role, campaign_id):
    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        membership_error = _require_campaign_member(conn, campaign, username)
        if membership_error is not None:
            return membership_error

        settings = conn.execute(
            "SELECT rules, tone, consent_json FROM play_session_zero WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
    finally:
        conn.close()

    if settings is None:
        return jsonify(error="session-zero not found"), 404

    return jsonify(
        rules=settings["rules"],
        tone=settings["tone"],
        consent=json.loads(settings["consent_json"]),
    ), 200


def _valid_tags(value, allow_empty):
    if not isinstance(value, list):
        return False
    if not value and not allow_empty:
        return False
    seen = set()
    for entry in value:
        if not isinstance(entry, str) or not entry.strip() or entry in seen:
            return False
        seen.add(entry)
    return True


def _serialize_content(row):
    return {
        "content_id": row["content_id"],
        "kind": row["kind"],
        "text": row["text"],
        "tags": json.loads(row["tags_json"]),
    }


@bp.post("/v1/play/campaigns/<campaign_id>/content")
@require_auth
def create_play_campaign_content(username, _role, campaign_id):
    data = request.get_json(silent=True) or {}
    content_id = data.get("content_id")
    kind = data.get("kind")
    text = data.get("text")
    tags = data.get("tags")

    if not valid_nonempty_str(content_id):
        return jsonify(error="invalid content_id"), 400
    if not valid_nonempty_str(kind):
        return jsonify(error="invalid kind"), 400
    if not valid_nonempty_str(text):
        return jsonify(error="invalid text"), 400
    if not _valid_tags(tags, allow_empty=False):
        return jsonify(error="invalid tags"), 400

    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        if campaign["owner"] != username:
            return jsonify(error="forbidden"), 403

        existing = conn.execute(
            "SELECT 1 FROM play_content WHERE campaign_id = ? AND content_id = ?",
            (campaign_id, content_id),
        ).fetchone()
        if existing is not None:
            return jsonify(error="content already exists"), 409

        conn.execute(
            "INSERT INTO play_content (campaign_id, content_id, kind, text, tags_json) "
            "VALUES (?, ?, ?, ?, ?)",
            (campaign_id, content_id, kind, text, json.dumps(tags)),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify(
        content_id=content_id, kind=kind, text=text, tags=tags
    ), 201


@bp.put("/v1/play/campaigns/<campaign_id>/content/<content_id>/tags")
@require_auth
def put_play_campaign_content_tags(username, _role, campaign_id, content_id):
    data = request.get_json(silent=True) or {}
    tags = data.get("tags")

    if not _valid_tags(tags, allow_empty=True):
        return jsonify(error="invalid tags"), 400

    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        if campaign["owner"] != username:
            return jsonify(error="forbidden"), 403

        record = conn.execute(
            "SELECT content_id, kind, text FROM play_content "
            "WHERE campaign_id = ? AND content_id = ?",
            (campaign_id, content_id),
        ).fetchone()
        if record is None:
            return jsonify(error="content not found"), 404

        conn.execute(
            "UPDATE play_content SET tags_json = ? WHERE campaign_id = ? AND content_id = ?",
            (json.dumps(tags), campaign_id, content_id),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify(
        content_id=record["content_id"], kind=record["kind"], text=record["text"], tags=tags
    ), 200


@bp.get("/v1/play/campaigns/<campaign_id>/content")
@require_auth
def list_play_campaign_content(username, _role, campaign_id):
    exclude_tag = request.args.get("exclude_tag")
    if exclude_tag is not None and not exclude_tag.strip():
        return jsonify(error="invalid exclude_tag"), 400

    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        membership_error = _require_campaign_member(conn, campaign, username)
        if membership_error is not None:
            return membership_error

        rows = conn.execute(
            "SELECT content_id, kind, text, tags_json FROM play_content "
            "WHERE campaign_id = ? ORDER BY id ASC",
            (campaign_id,),
        ).fetchall()
    finally:
        conn.close()

    is_dm = campaign["owner"] == username
    content = []
    for row in rows:
        entry = _serialize_content(row)
        if not is_dm and exclude_tag is not None and exclude_tag in entry["tags"]:
            continue
        content.append(entry)

    return jsonify(content=content), 200


VALID_NOTE_VISIBILITIES = frozenset({"private", "party"})


def _serialize_note(row):
    return {
        "note_id": row["note_id"],
        "text": row["text"],
        "visibility": row["visibility"],
        "owner": row["owner"],
    }


@bp.post("/v1/play/campaigns/<campaign_id>/notes")
@require_auth
def create_play_campaign_note(username, _role, campaign_id):
    data = request.get_json(silent=True) or {}
    note_id = data.get("note_id")
    text = data.get("text")
    visibility = data.get("visibility")

    if not valid_nonempty_str(note_id):
        return jsonify(error="invalid note_id"), 400
    if not valid_nonempty_str(text):
        return jsonify(error="invalid text"), 400
    if visibility not in VALID_NOTE_VISIBILITIES:
        return jsonify(error="invalid visibility"), 400

    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        membership_error = _require_campaign_member(conn, campaign, username)
        if membership_error is not None:
            return membership_error

        existing = conn.execute(
            "SELECT id FROM play_notes WHERE campaign_id = ? AND note_id = ?",
            (campaign_id, note_id),
        ).fetchone()
        if existing is not None:
            return jsonify(error="note already exists"), 409

        conn.execute(
            "INSERT INTO play_notes (campaign_id, note_id, text, visibility, owner) "
            "VALUES (?, ?, ?, ?, ?)",
            (campaign_id, note_id, text, visibility, username),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify(
        note_id=note_id, text=text, visibility=visibility, owner=username
    ), 201


@bp.get("/v1/play/campaigns/<campaign_id>/notes")
@require_auth
def list_play_campaign_notes(username, _role, campaign_id):
    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        membership_error = _require_campaign_member(conn, campaign, username)
        if membership_error is not None:
            return membership_error

        rows = conn.execute(
            "SELECT note_id, text, visibility, owner FROM play_notes "
            "WHERE campaign_id = ? ORDER BY id ASC",
            (campaign_id,),
        ).fetchall()
    finally:
        conn.close()

    is_dm = campaign["owner"] == username
    notes = []
    for row in rows:
        if is_dm or row["visibility"] == "party" or row["owner"] == username:
            notes.append(_serialize_note(row))

    return jsonify(notes=notes), 200


@bp.get("/v1/play/campaigns/<campaign_id>/notes/<note_id>")
@require_auth
def get_play_campaign_note(username, _role, campaign_id, note_id):
    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        membership_error = _require_campaign_member(conn, campaign, username)
        if membership_error is not None:
            return membership_error

        row = conn.execute(
            "SELECT note_id, text, visibility, owner FROM play_notes "
            "WHERE campaign_id = ? AND note_id = ?",
            (campaign_id, note_id),
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        return jsonify(error="note not found"), 404

    is_dm = campaign["owner"] == username
    if row["visibility"] == "private" and not is_dm and row["owner"] != username:
        return jsonify(error="forbidden"), 403

    return jsonify(_serialize_note(row)), 200


@bp.put("/v1/play/campaigns/<campaign_id>/notes/<note_id>")
@require_auth
def update_play_campaign_note(username, _role, campaign_id, note_id):
    data = request.get_json(silent=True) or {}
    text = data.get("text")
    visibility = data.get("visibility")

    if not valid_nonempty_str(text):
        return jsonify(error="invalid text"), 400
    if visibility not in VALID_NOTE_VISIBILITIES:
        return jsonify(error="invalid visibility"), 400

    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        membership_error = _require_campaign_member(conn, campaign, username)
        if membership_error is not None:
            return membership_error

        row = conn.execute(
            "SELECT note_id, owner FROM play_notes WHERE campaign_id = ? AND note_id = ?",
            (campaign_id, note_id),
        ).fetchone()
        if row is None:
            return jsonify(error="note not found"), 404

        if row["owner"] != username:
            return jsonify(error="forbidden"), 403

        conn.execute(
            "UPDATE play_notes SET text = ?, visibility = ? "
            "WHERE campaign_id = ? AND note_id = ?",
            (text, visibility, campaign_id, note_id),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify(
        note_id=note_id, text=text, visibility=visibility, owner=row["owner"]
    ), 200


def _serialize_whisper(row):
    return {
        "whisper_id": row["whisper_id"],
        "from_character_id": row["from_character_id"],
        "to_character_id": row["to_character_id"],
        "text": row["text"],
    }


@bp.post("/v1/play/campaigns/<campaign_id>/whispers")
@require_auth
def create_play_campaign_whisper(username, role, campaign_id):
    data = request.get_json(silent=True) or {}
    whisper_id = data.get("whisper_id")
    to_character_id = data.get("to_character_id")
    text = data.get("text")

    if not valid_nonempty_str(whisper_id):
        return jsonify(error="invalid whisper_id"), 400
    if not valid_nonempty_str(to_character_id):
        return jsonify(error="invalid to_character_id"), 400
    if not valid_nonempty_str(text):
        return jsonify(error="invalid text"), 400

    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        membership_error = _require_campaign_member(conn, campaign, username)
        if membership_error is not None:
            return membership_error

        if role != "player":
            return jsonify(error="forbidden"), 403

        sender = conn.execute(
            "SELECT character_id FROM play_members WHERE campaign_id = ? AND username = ?",
            (campaign_id, username),
        ).fetchone()
        if sender is None:
            return jsonify(error="forbidden"), 403

        from_character_id = sender["character_id"]

        recipient = conn.execute(
            "SELECT character_id FROM play_members WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, to_character_id),
        ).fetchone()
        if recipient is None:
            return jsonify(error="invalid to_character_id"), 400

        existing = conn.execute(
            "SELECT id FROM play_whispers WHERE campaign_id = ? AND whisper_id = ?",
            (campaign_id, whisper_id),
        ).fetchone()
        if existing is not None:
            return jsonify(error="whisper already exists"), 409

        conn.execute(
            "INSERT INTO play_whispers "
            "(campaign_id, whisper_id, from_character_id, to_character_id, text) "
            "VALUES (?, ?, ?, ?, ?)",
            (campaign_id, whisper_id, from_character_id, to_character_id, text),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify(
        whisper_id=whisper_id,
        from_character_id=from_character_id,
        to_character_id=to_character_id,
        text=text,
    ), 201


@bp.get("/v1/play/campaigns/<campaign_id>/whispers")
@require_auth
def list_play_campaign_whispers(username, _role, campaign_id):
    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        membership_error = _require_campaign_member(conn, campaign, username)
        if membership_error is not None:
            return membership_error

        is_dm = campaign["owner"] == username

        own_character_id = None
        if not is_dm:
            member = conn.execute(
                "SELECT character_id FROM play_members WHERE campaign_id = ? AND username = ?",
                (campaign_id, username),
            ).fetchone()
            own_character_id = member["character_id"] if member is not None else None

        rows = conn.execute(
            "SELECT whisper_id, from_character_id, to_character_id, text "
            "FROM play_whispers WHERE campaign_id = ? ORDER BY id ASC",
            (campaign_id,),
        ).fetchall()
    finally:
        conn.close()

    whispers = []
    for row in rows:
        if is_dm or row["from_character_id"] == own_character_id or row["to_character_id"] == own_character_id:
            whispers.append(_serialize_whisper(row))

    return jsonify(whispers=whispers), 200


@bp.get("/v1/play/campaigns/<campaign_id>/characters/<character_id>/sheet")
@require_auth
def get_play_campaign_character_sheet(username, _role, campaign_id, character_id):
    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        membership_error = _require_campaign_member(conn, campaign, username)
        if membership_error is not None:
            return membership_error

        member = conn.execute(
            "SELECT username, character_id, name, class, hp_max FROM play_members "
            "WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, character_id),
        ).fetchone()
        if member is None:
            return jsonify(error="character not found"), 404

        owner_record = conn.execute(
            "SELECT owner, class, level, proficiency_bonus, hp_max, dex_modifier "
            "FROM play_character_owners WHERE campaign_id = ? AND character_id = ?",
            (campaign_id, character_id),
        ).fetchone()
    finally:
        conn.close()

    owner = member["username"]
    if owner_record is not None and owner_record["owner"]:
        owner = owner_record["owner"]
    is_dm = campaign["owner"] == username
    if not is_dm and owner != username:
        return jsonify(error="forbidden"), 403

    char_class = member["class"]
    if owner_record is not None:
        char_class = owner_record["class"] or char_class

    return jsonify(
        character_id=character_id,
        owner=owner,
        name=member["name"],
        **{"class": char_class},
        level=1,
        proficiency_bonus=2,
        hp_max=10,
        armor_class=10,
    ), 200


def _serialize_invitation(row):
    return {
        "invitation_id": row["invitation_id"],
        "username": row["username"],
        "character_id": row["character_id"],
        "status": row["status"],
    }


@bp.post("/v1/play/campaigns/<campaign_id>/invitations")
@require_auth
def create_play_campaign_invitation(username, _role, campaign_id):
    data = request.get_json(silent=True) or {}
    invitation_id = data.get("invitation_id")
    target_username = data.get("username")
    character_id = data.get("character_id")

    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        if campaign["owner"] != username:
            return jsonify(error="forbidden"), 403

        if not valid_nonempty_str(invitation_id):
            return jsonify(error="invalid invitation_id"), 400
        if not valid_nonempty_str(target_username):
            return jsonify(error="invalid username"), 400
        if not valid_nonempty_str(character_id):
            return jsonify(error="invalid character_id"), 400

        target = conn.execute(
            "SELECT username, role FROM users WHERE username = ?", (target_username,)
        ).fetchone()
        if target is None or target["role"] != "player":
            return jsonify(error="invalid username"), 400

        existing_id = conn.execute(
            "SELECT id FROM play_invitations WHERE campaign_id = ? AND invitation_id = ?",
            (campaign_id, invitation_id),
        ).fetchone()
        if existing_id is not None:
            return jsonify(error="invitation already exists"), 409

        existing_pending = conn.execute(
            "SELECT id FROM play_invitations "
            "WHERE campaign_id = ? AND username = ? AND status = 'pending'",
            (campaign_id, target_username),
        ).fetchone()
        if existing_pending is not None:
            return jsonify(error="invitation already pending"), 409

        conn.execute(
            "INSERT INTO play_invitations "
            "(campaign_id, invitation_id, username, character_id, status) "
            "VALUES (?, ?, ?, ?, 'pending')",
            (campaign_id, invitation_id, target_username, character_id),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify(
        invitation_id=invitation_id,
        username=target_username,
        character_id=character_id,
        status="pending",
    ), 201


@bp.post("/v1/play/campaigns/<campaign_id>/invitations/<invitation_id>/accept")
@require_auth
def accept_play_campaign_invitation(username, _role, campaign_id, invitation_id):
    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        invitation = conn.execute(
            "SELECT invitation_id, username, character_id, status FROM play_invitations "
            "WHERE campaign_id = ? AND invitation_id = ?",
            (campaign_id, invitation_id),
        ).fetchone()
        if invitation is None:
            return jsonify(error="invitation not found"), 404

        if invitation["username"] != username:
            return jsonify(error="forbidden"), 403

        if invitation["status"] != "pending":
            return jsonify(error="invitation already resolved"), 409

        character_id = invitation["character_id"]

        existing_membership = conn.execute(
            "SELECT username FROM play_members WHERE campaign_id = ? AND username = ?",
            (campaign_id, username),
        ).fetchone()
        if existing_membership is None:
            conn.execute(
                "INSERT INTO play_members (campaign_id, username, character_id, name, class) "
                "VALUES (?, ?, ?, ?, ?)",
                (campaign_id, username, character_id, username, "unassigned"),
            )
            conn.execute(
                "INSERT INTO play_character_owners (campaign_id, character_id, owner, class) "
                "VALUES (?, ?, ?, ?)",
                (campaign_id, character_id, username, "unassigned"),
            )
            conn.execute(
                "INSERT INTO play_character_currency (campaign_id, character_id, gold) "
                "VALUES (?, ?, ?)",
                (campaign_id, character_id, 10),
            )

        conn.execute(
            "UPDATE play_invitations SET status = 'accepted' "
            "WHERE campaign_id = ? AND invitation_id = ?",
            (campaign_id, invitation_id),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify(
        invitation_id=invitation_id,
        username=username,
        character_id=character_id,
        status="accepted",
    ), 200


@bp.get("/v1/play/campaigns/<campaign_id>/invitations")
@require_auth
def list_play_campaign_invitations(username, _role, campaign_id):
    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        rows = conn.execute(
            "SELECT invitation_id, username, character_id, status FROM play_invitations "
            "WHERE campaign_id = ? ORDER BY id ASC",
            (campaign_id,),
        ).fetchall()
    finally:
        conn.close()

    is_dm = campaign["owner"] == username
    invitations = []
    for row in rows:
        if is_dm or row["username"] == username:
            invitations.append(_serialize_invitation(row))

    return jsonify(invitations=invitations), 200


def _valid_delegation_powers(powers):
    return (
        isinstance(powers, list)
        and bool(powers)
        and len(set(powers)) == len(powers)
        and all(power in VALID_DELEGATION_POWERS for power in powers)
    )


@bp.post("/v1/play/campaigns/<campaign_id>/delegations")
@require_auth
def grant_play_campaign_delegation(username, _role, campaign_id):
    data = request.get_json(silent=True) or {}
    target_username = data.get("username")
    powers = data.get("powers")

    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        if campaign["owner"] != username:
            return jsonify(error="forbidden"), 403

        if not valid_nonempty_str(target_username):
            return jsonify(error="invalid username"), 400
        if not _valid_delegation_powers(powers):
            return jsonify(error="invalid powers"), 400

        target_member = conn.execute(
            "SELECT username FROM play_members WHERE campaign_id = ? AND username = ?",
            (campaign_id, target_username),
        ).fetchone()
        if target_member is None:
            return jsonify(error="invalid username"), 400

        existing = conn.execute(
            "SELECT active FROM play_delegations WHERE campaign_id = ? AND username = ?",
            (campaign_id, target_username),
        ).fetchone()
        if existing is not None and existing["active"]:
            return jsonify(error="delegation already active"), 409

        powers_json = json.dumps(powers)
        if existing is None:
            conn.execute(
                "INSERT INTO play_delegations (campaign_id, username, powers, active) "
                "VALUES (?, ?, ?, 1)",
                (campaign_id, target_username, powers_json),
            )
        else:
            conn.execute(
                "UPDATE play_delegations SET powers = ?, active = 1 "
                "WHERE campaign_id = ? AND username = ?",
                (powers_json, campaign_id, target_username),
            )

        conn.execute(
            "INSERT INTO play_delegation_audit (campaign_id, username, action, powers) "
            "VALUES (?, ?, 'granted', ?)",
            (campaign_id, target_username, powers_json),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify(username=target_username, powers=powers, active=True), 201


@bp.delete("/v1/play/campaigns/<campaign_id>/delegations/<target_username>")
@require_auth
def revoke_play_campaign_delegation(username, _role, campaign_id, target_username):
    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        if campaign["owner"] != username:
            return jsonify(error="forbidden"), 403

        existing = conn.execute(
            "SELECT powers, active FROM play_delegations "
            "WHERE campaign_id = ? AND username = ?",
            (campaign_id, target_username),
        ).fetchone()
        if existing is None or not existing["active"]:
            return jsonify(error="delegation not found"), 404

        conn.execute(
            "UPDATE play_delegations SET active = 0 "
            "WHERE campaign_id = ? AND username = ?",
            (campaign_id, target_username),
        )
        conn.execute(
            "INSERT INTO play_delegation_audit (campaign_id, username, action, powers) "
            "VALUES (?, ?, 'revoked', ?)",
            (campaign_id, target_username, existing["powers"]),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify(
        username=target_username,
        powers=json.loads(existing["powers"]),
        active=False,
    ), 200


@bp.get("/v1/play/campaigns/<campaign_id>/delegations/audit")
@require_auth
def get_play_campaign_delegation_audit(username, _role, campaign_id):
    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        if campaign["owner"] != username:
            return jsonify(error="forbidden"), 403

        rows = conn.execute(
            "SELECT username, action, powers FROM play_delegation_audit "
            "WHERE campaign_id = ? ORDER BY id ASC",
            (campaign_id,),
        ).fetchall()
    finally:
        conn.close()

    entries = [
        {
            "username": row["username"],
            "action": row["action"],
            "powers": json.loads(row["powers"]),
        }
        for row in rows
    ]
    return jsonify(entries=entries), 200


def _serialize_audit_event(row):
    return {
        "kind": row["kind"],
        "actor": row["actor"],
        "role": row["role"],
        "timestamp": row["timestamp"],
        "correlation_id": row["correlation_id"],
    }


@bp.post("/v1/play/campaigns/<campaign_id>/audit-events")
@require_auth
def create_play_campaign_audit_event(username, _role, campaign_id):
    data = request.get_json(silent=True) or {}
    kind = data.get("kind")
    correlation_id = data.get("correlation_id")

    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        is_owner = campaign["owner"] == username
        is_member = conn.execute(
            "SELECT 1 FROM play_members WHERE campaign_id = ? AND username = ?",
            (campaign_id, username),
        ).fetchone()
        if not is_owner and is_member is None:
            return jsonify(error="not a campaign member"), 403

        if not valid_nonempty_str(kind) or not valid_nonempty_str(correlation_id):
            return jsonify(error="invalid payload"), 400

        existing = conn.execute(
            "SELECT 1 FROM play_audit_events WHERE campaign_id = ? AND correlation_id = ?",
            (campaign_id, correlation_id),
        ).fetchone()
        if existing is not None:
            return jsonify(error="duplicate correlation_id"), 409

        last_timestamp = conn.execute(
            "SELECT MAX(timestamp) AS t FROM play_audit_events WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()["t"]
        timestamp = (last_timestamp or 0) + 1
        role = "DM" if is_owner else "player"

        conn.execute(
            "INSERT INTO play_audit_events "
            "(campaign_id, timestamp, kind, actor, role, correlation_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (campaign_id, timestamp, kind, username, role, correlation_id),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify(
        kind=kind,
        actor=username,
        role=role,
        timestamp=timestamp,
        correlation_id=correlation_id,
    ), 201


@bp.get("/v1/play/campaigns/<campaign_id>/audit-events")
@require_auth
def list_play_campaign_audit_events(username, _role, campaign_id):
    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        is_owner = campaign["owner"] == username
        is_member = conn.execute(
            "SELECT 1 FROM play_members WHERE campaign_id = ? AND username = ?",
            (campaign_id, username),
        ).fetchone()
        if not is_owner and is_member is None:
            return jsonify(error="not a campaign member"), 403
        if not is_owner:
            return jsonify(error="forbidden"), 403

        rows = conn.execute(
            "SELECT kind, actor, role, timestamp, correlation_id "
            "FROM play_audit_events WHERE campaign_id = ? ORDER BY timestamp ASC",
            (campaign_id,),
        ).fetchall()
    finally:
        conn.close()

    entries = [_serialize_audit_event(row) for row in rows]
    return jsonify(entries=entries), 200


VALID_PROJECTION_EVENT_KINDS = frozenset({"set-story", "increment-danger"})


def next_projection_sequence(conn, campaign_id):
    last_sequence = conn.execute(
        "SELECT MAX(sequence) AS s FROM play_projection_events WHERE campaign_id = ?",
        (campaign_id,),
    ).fetchone()["s"]
    return (last_sequence or 0) + 1


def _rebuild_projection(conn, campaign_id):
    rows = conn.execute(
        "SELECT event_id, kind, value FROM play_projection_events "
        "WHERE campaign_id = ? ORDER BY sequence ASC",
        (campaign_id,),
    ).fetchall()

    story = ""
    danger = 0
    applied_event_ids = []
    for row in rows:
        if row["kind"] == "set-story":
            story = row["value"]
        elif row["kind"] == "increment-danger":
            danger += 1
        applied_event_ids.append(row["event_id"])

    return {"story": story, "danger": danger, "applied_event_ids": applied_event_ids}


@bp.post("/v1/play/campaigns/<campaign_id>/projection-events")
@require_auth
def create_play_campaign_projection_event(username, _role, campaign_id):
    data = request.get_json(silent=True) or {}
    event_id = data.get("event_id")
    kind = data.get("kind")
    value = data.get("value")

    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        is_owner = campaign["owner"] == username
        is_member = conn.execute(
            "SELECT 1 FROM play_members WHERE campaign_id = ? AND username = ?",
            (campaign_id, username),
        ).fetchone()
        if not is_owner and is_member is None:
            return jsonify(error="not a campaign member"), 403
        if is_owner:
            return jsonify(error="forbidden"), 403

        if not isinstance(event_id, str) or not event_id:
            return jsonify(error="invalid event_id"), 400
        if kind not in VALID_PROJECTION_EVENT_KINDS:
            return jsonify(error="invalid kind"), 400
        if kind == "set-story":
            if not valid_nonempty_str(value):
                return jsonify(error="invalid value"), 400
        elif value is not None:
            return jsonify(error="invalid value"), 400

        existing = conn.execute(
            "SELECT 1 FROM play_projection_events WHERE campaign_id = ? AND event_id = ?",
            (campaign_id, event_id),
        ).fetchone()
        if existing is not None:
            return jsonify(error="duplicate event_id"), 409

        sequence = next_projection_sequence(conn, campaign_id)
        stored_value = value if kind == "set-story" else None

        conn.execute(
            "INSERT INTO play_projection_events "
            "(campaign_id, sequence, event_id, kind, value) VALUES (?, ?, ?, ?, ?)",
            (campaign_id, sequence, event_id, kind, stored_value),
        )
        conn.commit()
    finally:
        conn.close()

    result = {"sequence": sequence, "event_id": event_id, "kind": kind}
    if kind == "set-story":
        result["value"] = stored_value
    return jsonify(**result), 201


@bp.get("/v1/play/campaigns/<campaign_id>/projection")
@require_auth
def get_play_campaign_projection(username, _role, campaign_id):
    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        is_owner = campaign["owner"] == username
        is_member = conn.execute(
            "SELECT 1 FROM play_members WHERE campaign_id = ? AND username = ?",
            (campaign_id, username),
        ).fetchone()
        if not is_owner and is_member is None:
            return jsonify(error="not a campaign member"), 403

        projection = _rebuild_projection(conn, campaign_id)
    finally:
        conn.close()

    return jsonify(**projection), 200


@bp.get("/v1/play/campaigns/<campaign_id>/projection/rebuild")
@require_auth
def rebuild_play_campaign_projection(username, _role, campaign_id):
    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            return jsonify(error="campaign not found"), 404

        is_owner = campaign["owner"] == username
        is_member = conn.execute(
            "SELECT 1 FROM play_members WHERE campaign_id = ? AND username = ?",
            (campaign_id, username),
        ).fetchone()
        if not is_owner and is_member is None:
            return jsonify(error="not a campaign member"), 403

        projection = _rebuild_projection(conn, campaign_id)
    finally:
        conn.close()

    return jsonify(**projection), 200
