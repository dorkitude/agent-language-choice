"""Django views for the D&D REST API.

Each view is a thin layer over the ``domain`` and ``db`` modules. Common
request parsing and response helpers live in ``dndsite.http``. Validation
failures return 400, missing resources 404, and conflicts 409. Error message
strings are preserved from the original implementation to maintain exact
response bodies.
"""

import json

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from .common import _get_actor, require_actor

from ..http import bad_request, conflict, forbidden, not_found, parse_json, require_method, unauthorized

from ..db import db_conn

# ---------------------------------------------------------------------------
# Encounters
# ---------------------------------------------------------------------------


@csrf_exempt
def create_encounter(request, id):
    bad = require_method(request, "POST")
    if bad:
        return bad

    actor, err = require_actor(request, "dm")
    if err is not None:
        return err

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")
    try:
        encounter_id = body["id"]
        name = body["name"]
        if not isinstance(encounter_id, str) or not isinstance(name, str):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    with db_conn() as conn:
        campaign = conn.execute(
            "SELECT id, owner, current_actor FROM play_campaigns WHERE id = ?", (id,)
        ).fetchone()
        if campaign is None:
            return not_found("campaign not found")

        if actor["username"] != campaign["owner"]:
            return forbidden()

        duplicate = conn.execute(
            "SELECT 1 FROM encounters WHERE id = ?", (encounter_id,)
        ).fetchone()
        if duplicate is not None:
            return conflict("encounter already exists")

        active = conn.execute(
            "SELECT 1 FROM encounters WHERE campaign_id = ? AND status = ?",
            (id, "active"),
        ).fetchone()
        if active is not None:
            return conflict("campaign already in combat")

        conn.execute(
            "UPDATE play_campaigns SET phase = ?, saved_actor = ? WHERE id = ?",
            ("combat", campaign["current_actor"], id),
        )

        conn.execute(
            "INSERT INTO encounters (id, campaign_id, name, status, combatants_json, conditions_json, order_json, round, turn_index) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (encounter_id, id, name, "active", "[]", "{}", "[]", 1, 0),
        )

    return JsonResponse(
        {
            "id": encounter_id,
            "name": name,
            "status": "active",
            "combatants": [],
        },
        status=201,
    )



# ---------------------------------------------------------------------------
# Encounter monsters
# ---------------------------------------------------------------------------


@csrf_exempt
def add_monster(request, id, enc_id):
    bad = require_method(request, "POST")
    if bad:
        return bad

    actor, err = require_actor(request, "dm")
    if err is not None:
        return err

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")
    try:
        monster_id = body["monster_id"]
        name = body["name"]
        hp_max = body["hp_max"]
        initiative = body["initiative"]
        if not all(isinstance(v, str) for v in (monster_id, name)):
            raise ValueError
        if not isinstance(hp_max, int) or not isinstance(initiative, int):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    with db_conn() as conn:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (id,)
        ).fetchone()
        if campaign is None:
            return not_found("campaign not found")

        if actor["username"] != campaign["owner"]:
            return forbidden()

        encounter = conn.execute(
            "SELECT id, campaign_id, combatants_json FROM encounters WHERE id = ?",
            (enc_id,),
        ).fetchone()
        if encounter is None:
            return not_found("encounter not found")
        if encounter["campaign_id"] != id:
            return not_found("encounter not found")

        combatants = json.loads(encounter["combatants_json"])
        if any(c.get("monster_id") == monster_id for c in combatants):
            return conflict("monster already exists")

        combatants.append(
            {
                "monster_id": monster_id,
                "name": name,
                "hp_max": hp_max,
                "hp_current": hp_max,
                "initiative": initiative,
            }
        )

        conn.execute(
            "UPDATE encounters SET combatants_json = ?, order_json = ? WHERE id = ?",
            (json.dumps(combatants), _fresh_encounter_order_json(combatants), enc_id),
        )

    return JsonResponse(
        {
            "monster_id": monster_id,
            "name": name,
            "hp_max": hp_max,
            "initiative": initiative,
            "hp_current": hp_max,
        },
        status=201,
    )


@csrf_exempt
def remove_monster(request, id, enc_id, monster_id):
    bad = require_method(request, "DELETE")
    if bad:
        return bad

    actor, err = require_actor(request, "dm")
    if err is not None:
        return err

    with db_conn() as conn:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (id,)
        ).fetchone()
        if campaign is None:
            return not_found("campaign not found")

        if actor["username"] != campaign["owner"]:
            return forbidden()

        encounter = conn.execute(
            "SELECT id, campaign_id, combatants_json FROM encounters WHERE id = ?",
            (enc_id,),
        ).fetchone()
        if encounter is None:
            return not_found("encounter not found")
        if encounter["campaign_id"] != id:
            return not_found("encounter not found")

        combatants = json.loads(encounter["combatants_json"])
        new_combatants = [c for c in combatants if c.get("monster_id") != monster_id]
        if len(new_combatants) == len(combatants):
            return not_found("monster not found")

        conn.execute(
            "UPDATE encounters SET combatants_json = ?, order_json = ? WHERE id = ?",
            (json.dumps(new_combatants), _fresh_encounter_order_json(new_combatants), enc_id),
        )

    return JsonResponse({"removed": monster_id})



# ---------------------------------------------------------------------------
# Party/encounter combatant binding
# ---------------------------------------------------------------------------


@csrf_exempt
def bind_member(request, id, enc_id):
    bad = require_method(request, "POST")
    if bad:
        return bad

    actor, err = require_actor(request, "dm")
    if err is not None:
        return err

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")
    try:
        member = body["member"]
        initiative = body["initiative"]
        if not isinstance(member, str) or not isinstance(initiative, int):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    with db_conn() as conn:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (id,)
        ).fetchone()
        if campaign is None:
            return not_found("campaign not found")

        if actor["username"] != campaign["owner"]:
            return forbidden()

        encounter = conn.execute(
            "SELECT id, campaign_id, combatants_json FROM encounters WHERE id = ?",
            (enc_id,),
        ).fetchone()
        if encounter is None or encounter["campaign_id"] != id:
            return not_found("encounter not found")

        member_row = conn.execute(
            "SELECT username, character_id, name FROM play_campaign_members "
            "WHERE campaign_id = ? AND username = ?",
            (id, member),
        ).fetchone()
        if member_row is None:
            return bad_request("invalid member")

        combatants = json.loads(encounter["combatants_json"])
        if any(c.get("member") == member for c in combatants):
            return conflict("member already bound")

        combatants.append(
            {
                "member": member,
                "character_id": member_row["character_id"],
                "name": member_row["name"],
                "initiative": initiative,
            }
        )

        conn.execute(
            "UPDATE encounters SET combatants_json = ?, order_json = ? WHERE id = ?",
            (json.dumps(combatants), _fresh_encounter_order_json(combatants), enc_id),
        )

    return JsonResponse(
        {
            "member": member,
            "character_id": member_row["character_id"],
            "name": member_row["name"],
            "initiative": initiative,
        },
        status=201,
    )


@csrf_exempt
def unbind_member(request, id, enc_id, member):
    bad = require_method(request, "DELETE")
    if bad:
        return bad

    actor, err = require_actor(request, "dm")
    if err is not None:
        return err

    with db_conn() as conn:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (id,)
        ).fetchone()
        if campaign is None:
            return not_found("campaign not found")

        if actor["username"] != campaign["owner"]:
            return forbidden()

        encounter = conn.execute(
            "SELECT id, campaign_id, combatants_json FROM encounters WHERE id = ?",
            (enc_id,),
        ).fetchone()
        if encounter is None or encounter["campaign_id"] != id:
            return not_found("encounter not found")

        combatants = json.loads(encounter["combatants_json"])
        new_combatants = [c for c in combatants if c.get("member") != member]
        if len(new_combatants) == len(combatants):
            return not_found("member not found")

        conn.execute(
            "UPDATE encounters SET combatants_json = ?, order_json = ? WHERE id = ?",
            (json.dumps(new_combatants), _fresh_encounter_order_json(new_combatants), enc_id),
        )

    return JsonResponse({"removed": member})



# ---------------------------------------------------------------------------
# Encounter turns
# ---------------------------------------------------------------------------


def _encounter_initiative_order(combatants, order_json=None):
    """Return combatants sorted by initiative descending, then name ascending.

    If ``order_json`` is provided and non-empty, it is a list of combatant keys
    (``monster_id`` or ``member``) that defines the explicit turn order.  Missing
    or extra combatants fall back to initiative order.
    """
    by_initiative = sorted(combatants, key=lambda c: (-c["initiative"], c["name"]))
    if not order_json:
        return by_initiative
    ordered_keys = json.loads(order_json)
    if not ordered_keys:
        return by_initiative
    combatant_map = {}
    for c in combatants:
        key = _encounter_target_key(c)
        if key:
            combatant_map[key] = c
    result = []
    seen = set()
    for key in ordered_keys:
        if key in combatant_map and key not in seen:
            result.append(combatant_map[key])
            seen.add(key)
    for c in by_initiative:
        key = _encounter_target_key(c)
        if key and key not in seen:
            result.append(c)
            seen.add(key)
    return result


def _fresh_encounter_order_json(combatants):
    """Return an order_json value sorted by initiative, then name."""
    order = _encounter_initiative_order(combatants)
    return json.dumps([_encounter_target_key(c) for c in order])


def _active_combatant_info(combatant):
    """Return the public summary for a combatant in the turn response."""
    if "monster_id" in combatant:
        kind = "monster"
    elif "member" in combatant or "character_id" in combatant:
        kind = "player"
    else:
        kind = "unknown"
    return {"name": combatant["name"], "kind": kind, "initiative": combatant["initiative"]}


def _encounter_actor_can_advance(actor, campaign, active_combatant):
    """Return True if the actor may advance the encounter turn."""
    if actor["username"] == campaign["owner"]:
        return True
    if active_combatant is None:
        return False
    controller = active_combatant.get("member") or active_combatant.get("character_id")
    if controller is None:
        return False
    return actor["username"] == controller


@csrf_exempt
def get_encounter_turn(request, id, enc_id):
    bad = require_method(request, "GET")
    if bad:
        return bad

    actor, err = require_actor(request)
    if err is not None:
        return err

    with db_conn() as conn:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (id,)
        ).fetchone()
        if campaign is None:
            return not_found("campaign not found")

        is_member = (
            conn.execute(
                "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
                (id, actor["username"]),
            ).fetchone()
            is not None
        )
        if actor["username"] != campaign["owner"] and not is_member:
            return forbidden()

        encounter = conn.execute(
            "SELECT id, campaign_id, round, turn_index, combatants_json, order_json FROM encounters WHERE id = ?",
            (enc_id,),
        ).fetchone()
        if encounter is None or encounter["campaign_id"] != id:
            return not_found("encounter not found")

        combatants = json.loads(encounter["combatants_json"])
        order = _encounter_initiative_order(combatants, encounter["order_json"])
        active = order[encounter["turn_index"]] if order else None

    return JsonResponse(
        {
            "round": encounter["round"],
            "turn_index": encounter["turn_index"],
            "active": _active_combatant_info(active) if active else None,
        }
    )


@csrf_exempt
def advance_encounter_turn(request, id, enc_id):
    bad = require_method(request, "POST")
    if bad:
        return bad

    actor, err = require_actor(request)
    if err is not None:
        return err

    with db_conn() as conn:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (id,)
        ).fetchone()
        if campaign is None:
            return not_found("campaign not found")

        encounter = conn.execute(
            "SELECT id, campaign_id, round, turn_index, combatants_json, order_json, conditions_json FROM encounters WHERE id = ?",
            (enc_id,),
        ).fetchone()
        if encounter is None or encounter["campaign_id"] != id:
            return not_found("encounter not found")

        combatants = json.loads(encounter["combatants_json"])
        order = _encounter_initiative_order(combatants, encounter["order_json"])
        if not order:
            return conflict("not your turn")

        active = order[encounter["turn_index"]]
        if not _encounter_actor_can_advance(actor, campaign, active):
            return conflict("not your turn")

        turn_index = encounter["turn_index"] + 1
        round_num = encounter["round"]
        if turn_index >= len(order):
            turn_index = 0
            round_num += 1

        new_active = order[turn_index]

        # Conditions on the new active combatant decrement at the start of its turn.
        conditions = json.loads(encounter["conditions_json"])
        target_key = new_active.get("monster_id") or new_active.get("member")
        if target_key is not None and target_key in conditions:
            new_conditions = []
            for cond in conditions[target_key]:
                cond["remaining_rounds"] -= 1
                if cond["remaining_rounds"] > 0:
                    new_conditions.append(cond)
            conditions[target_key] = new_conditions

        conn.execute(
            "UPDATE encounters SET round = ?, turn_index = ?, conditions_json = ? WHERE id = ?",
            (round_num, turn_index, json.dumps(conditions), enc_id),
        )

    return JsonResponse(
        {
            "round": round_num,
            "turn_index": turn_index,
            "active": _active_combatant_info(new_active),
        }
    )


@csrf_exempt
def delay_turn(request, id, enc_id):
    bad = require_method(request, "POST")
    if bad:
        return bad

    actor, err = require_actor(request)
    if err is not None:
        return err

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")
    try:
        new_index = int(body["new_index"])
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    with db_conn() as conn:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (id,)
        ).fetchone()
        if campaign is None:
            return not_found("campaign not found")

        is_member = (
            conn.execute(
                "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
                (id, actor["username"]),
            ).fetchone()
            is not None
        )
        if actor["username"] != campaign["owner"] and not is_member:
            return forbidden()

        encounter = conn.execute(
            "SELECT id, campaign_id, round, turn_index, combatants_json, order_json "
            "FROM encounters WHERE id = ?",
            (enc_id,),
        ).fetchone()
        if encounter is None or encounter["campaign_id"] != id:
            return not_found("encounter not found")

        combatants = json.loads(encounter["combatants_json"])
        order = _encounter_initiative_order(combatants, encounter["order_json"])
        if not order:
            return bad_request("invalid request")

        turn_index = encounter["turn_index"]
        active = order[turn_index]
        if not _encounter_actor_can_advance(actor, campaign, active):
            return conflict("not your turn")

        if not (turn_index < new_index < len(order)):
            return bad_request("invalid index")

        current = order[turn_index]
        new_order = order[:turn_index] + order[turn_index + 1:]
        new_order.insert(new_index, current)
        new_turn_index = new_index

        conn.execute(
            "UPDATE encounters SET order_json = ?, turn_index = ? WHERE id = ?",
            (json.dumps([_encounter_target_key(c) for c in new_order]), new_turn_index, enc_id),
        )

    return JsonResponse(
        {
            "round": encounter["round"],
            "turn_index": new_turn_index,
            "active": _active_combatant_info(new_order[new_turn_index]),
            "order": [_active_combatant_info(c) for c in new_order],
        }
    )


@csrf_exempt
def ready_turn(request, id, enc_id):
    bad = require_method(request, "POST")
    if bad:
        return bad

    actor, err = require_actor(request)
    if err is not None:
        return err

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")
    try:
        trigger = body["trigger"]
        if not isinstance(trigger, str):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    with db_conn() as conn:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (id,)
        ).fetchone()
        if campaign is None:
            return not_found("campaign not found")

        is_member = (
            conn.execute(
                "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
                (id, actor["username"]),
            ).fetchone()
            is not None
        )
        if actor["username"] != campaign["owner"] and not is_member:
            return forbidden()

        encounter = conn.execute(
            "SELECT id, campaign_id, round, turn_index, combatants_json, order_json "
            "FROM encounters WHERE id = ?",
            (enc_id,),
        ).fetchone()
        if encounter is None or encounter["campaign_id"] != id:
            return not_found("encounter not found")

        combatants = json.loads(encounter["combatants_json"])
        order = _encounter_initiative_order(combatants, encounter["order_json"])
        if not order:
            return bad_request("invalid request")

        turn_index = encounter["turn_index"]
        active = order[turn_index]
        controller = active.get("member") or active.get("character_id")
        if controller is None or actor["username"] != controller:
            return conflict("not your turn")

        conn.execute(
            "INSERT INTO readied_actions (encounter_id, actor, trigger) VALUES (?, ?, ?)",
            (enc_id, actor["username"], trigger),
        )

    return JsonResponse(
        {
            "actor": actor["username"],
            "trigger": trigger,
        },
        status=201,
    )


@csrf_exempt
def submit_combat_action(request, id, enc_id):
    bad = require_method(request, "POST")
    if bad:
        return bad

    actor, err = require_actor(request)
    if err is not None:
        return err

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")
    try:
        action_type = body["type"]
        target = body["target"]
        text = body["text"]
        if not all(isinstance(v, str) for v in (action_type, target, text)):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    if action_type not in ("attack", "help", "dodge", "ready"):
        return bad_request("invalid request")

    with db_conn() as conn:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (id,)
        ).fetchone()
        if campaign is None:
            return not_found("campaign not found")

        is_member = (
            conn.execute(
                "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
                (id, actor["username"]),
            ).fetchone()
            is not None
        )
        if actor["username"] != campaign["owner"] and not is_member:
            return forbidden()

        encounter = conn.execute(
            "SELECT id, campaign_id, round, turn_index, combatants_json, order_json FROM encounters WHERE id = ?",
            (enc_id,),
        ).fetchone()
        if encounter is None or encounter["campaign_id"] != id:
            return not_found("encounter not found")

        combatants = json.loads(encounter["combatants_json"])
        order = _encounter_initiative_order(combatants, encounter["order_json"])
        if not order:
            return conflict("not your turn")

        active = order[encounter["turn_index"]]
        controller = active.get("member") or active.get("character_id")
        if controller is None:
            # Monster turn: only the DM may submit the action.
            if actor["username"] != campaign["owner"]:
                return conflict("not your turn")
        elif actor["username"] != controller:
            return conflict("not your turn")

        next_sequence = conn.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 AS next_sequence FROM narrations WHERE campaign_id = ?",
            (id,),
        ).fetchone()["next_sequence"]

        conn.execute(
            "INSERT INTO narrations (campaign_id, sequence, kind, type, actor, text, target) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (id, next_sequence, "combat_action", action_type, actor["username"], text, target),
        )

    return JsonResponse(
        {
            "sequence": next_sequence,
            "kind": "combat_action",
            "actor": actor["username"],
            "type": action_type,
            "target": target,
            "text": text,
        },
        status=201,
    )



# ---------------------------------------------------------------------------
# Damage and healing
# ---------------------------------------------------------------------------


def _require_owner_campaign_and_encounter(request, id, enc_id):
    """Validate that the actor owns the campaign and the encounter belongs to it.

    Returns a tuple ``(actor, campaign, encounter, error_response)``.  Exactly
    one of ``error_response`` or the first three items is non-None.
    """
    actor = _get_actor(request)
    if actor is None:
        return None, None, None, unauthorized("invalid credentials")

    with db_conn() as conn:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (id,)
        ).fetchone()
        if campaign is None:
            return None, None, None, not_found("campaign not found")

        if actor["role"] != "dm" or actor["username"] != campaign["owner"]:
            return None, None, None, forbidden()

        encounter = conn.execute(
            "SELECT id, campaign_id, combatants_json FROM encounters WHERE id = ?",
            (enc_id,),
        ).fetchone()
        if encounter is None or encounter["campaign_id"] != id:
            return None, None, None, not_found("encounter not found")

    return actor, campaign, encounter, None


@csrf_exempt
def damage(request, id, enc_id):
    bad = require_method(request, "POST")
    if bad:
        return bad

    actor, campaign, encounter, err = _require_owner_campaign_and_encounter(request, id, enc_id)
    if err is not None:
        return err

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")
    try:
        target = body["target"]
        amount = body["amount"]
        if not isinstance(target, str) or not isinstance(amount, int) or amount <= 0:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    with db_conn() as conn:
        encounter = conn.execute(
            "SELECT id, campaign_id, combatants_json FROM encounters WHERE id = ?",
            (enc_id,),
        ).fetchone()

        combatants = json.loads(encounter["combatants_json"])

        # Locate the target in the combatant list.  Monsters are keyed by
        # ``monster_id``; bound party members are keyed by ``member`` username.
        monster = None
        member_username = None
        for c in combatants:
            if c.get("monster_id") == target:
                monster = c
                break
            if c.get("member") == target:
                member_username = target
                break

        if monster is None and member_username is None:
            return not_found("target not found")

        if monster is not None:
            hp_before = monster.get("hp_current", monster["hp_max"])
            hp_after = max(0, hp_before - amount)
            actual_damage = hp_before - hp_after
            monster["hp_current"] = hp_after
            conn.execute(
                "UPDATE encounters SET combatants_json = ? WHERE id = ?",
                (json.dumps(combatants), enc_id),
            )
        else:
            member = conn.execute(
                "SELECT hp_current, hp_max FROM play_campaign_members "
                "WHERE campaign_id = ? AND username = ?",
                (id, member_username),
            ).fetchone()
            if member is None:
                return not_found("target not found")
            hp_before = member["hp_current"]
            hp_after = max(0, hp_before - amount)
            actual_damage = hp_before - hp_after
            new_status = "conscious" if hp_after > 0 else "unconscious"
            conn.execute(
                "UPDATE play_campaign_members SET hp_current = ?, status = ?, death_save_successes = 0, death_save_failures = 0 WHERE campaign_id = ? AND username = ?",
                (hp_after, new_status, id, member_username),
            )

    return JsonResponse(
        {
            "target": target,
            "hp_before": hp_before,
            "hp_after": hp_after,
            "damage": actual_damage,
        }
    )


@csrf_exempt
def heal(request, id, enc_id):
    bad = require_method(request, "POST")
    if bad:
        return bad

    actor, campaign, encounter, err = _require_owner_campaign_and_encounter(request, id, enc_id)
    if err is not None:
        return err

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")
    try:
        target = body["target"]
        amount = body["amount"]
        if not isinstance(target, str) or not isinstance(amount, int) or amount <= 0:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    with db_conn() as conn:
        encounter = conn.execute(
            "SELECT id, campaign_id, combatants_json FROM encounters WHERE id = ?",
            (enc_id,),
        ).fetchone()

        combatants = json.loads(encounter["combatants_json"])

        monster = None
        member_username = None
        for c in combatants:
            if c.get("monster_id") == target:
                monster = c
                break
            if c.get("member") == target:
                member_username = target
                break

        if monster is None and member_username is None:
            return not_found("target not found")

        if monster is not None:
            hp_max = monster["hp_max"]
            hp_before = monster.get("hp_current", hp_max)
            hp_after = min(hp_max, hp_before + amount)
            actual_healing = hp_after - hp_before
            monster["hp_current"] = hp_after
            conn.execute(
                "UPDATE encounters SET combatants_json = ? WHERE id = ?",
                (json.dumps(combatants), enc_id),
            )
        else:
            member = conn.execute(
                "SELECT hp_current, hp_max FROM play_campaign_members "
                "WHERE campaign_id = ? AND username = ?",
                (id, member_username),
            ).fetchone()
            if member is None:
                return not_found("target not found")
            hp_max = member["hp_max"]
            hp_before = member["hp_current"]
            hp_after = min(hp_max, hp_before + amount)
            actual_healing = hp_after - hp_before
            new_status = "conscious" if hp_after > 0 else "unconscious"
            conn.execute(
                "UPDATE play_campaign_members SET hp_current = ?, status = ?, death_save_successes = 0, death_save_failures = 0 WHERE campaign_id = ? AND username = ?",
                (hp_after, new_status, id, member_username),
            )

    return JsonResponse(
        {
            "target": target,
            "hp_before": hp_before,
            "hp_after": hp_after,
            "healing": actual_healing,
        }
    )



# ---------------------------------------------------------------------------
# Encounter conditions
# ---------------------------------------------------------------------------


def _encounter_target_key(combatant):
    """Return the conditions-map key for a combatant."""
    return combatant.get("monster_id") or combatant.get("member")


@csrf_exempt
def add_encounter_condition(request, id, enc_id):
    bad = require_method(request, "POST")
    if bad:
        return bad

    actor, err = require_actor(request, "dm")
    if err is not None:
        return err

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")
    try:
        target = str(body["target"])
        condition = str(body["condition"])
        duration = int(body["duration_rounds"])
        if duration <= 0:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    with db_conn() as conn:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (id,)
        ).fetchone()
        if campaign is None:
            return not_found("campaign not found")

        if actor["username"] != campaign["owner"]:
            return forbidden()

        encounter = conn.execute(
            "SELECT id, campaign_id, combatants_json, conditions_json FROM encounters WHERE id = ?",
            (enc_id,),
        ).fetchone()
        if encounter is None or encounter["campaign_id"] != id:
            return not_found("encounter not found")

        combatants = json.loads(encounter["combatants_json"])
        if not any(_encounter_target_key(c) == target for c in combatants):
            return bad_request("invalid target")

        conditions = json.loads(encounter["conditions_json"])
        conditions.setdefault(target, []).append(
            {"condition": condition, "remaining_rounds": duration}
        )

        conn.execute(
            "UPDATE encounters SET conditions_json = ? WHERE id = ?",
            (json.dumps(conditions), enc_id),
        )

    return JsonResponse(
        {"target": target, "conditions": conditions[target]}, status=201
    )


@csrf_exempt
def get_encounter_status(request, id, enc_id):
    bad = require_method(request, "GET")
    if bad:
        return bad

    actor, err = require_actor(request)
    if err is not None:
        return err

    with db_conn() as conn:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (id,)
        ).fetchone()
        if campaign is None:
            return not_found("campaign not found")

        is_member = (
            conn.execute(
                "SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?",
                (id, actor["username"]),
            ).fetchone()
            is not None
        )
        if actor["username"] != campaign["owner"] and not is_member:
            return forbidden()

        encounter = conn.execute(
            "SELECT id, campaign_id, name, status, round, turn_index, combatants_json, order_json, conditions_json "
            "FROM encounters WHERE id = ?",
            (enc_id,),
        ).fetchone()
        if encounter is None or encounter["campaign_id"] != id:
            return not_found("encounter not found")

        combatants = json.loads(encounter["combatants_json"])
        order = _encounter_initiative_order(combatants, encounter["order_json"])
        active = order[encounter["turn_index"]] if order else None

    return JsonResponse(
        {
            "id": encounter["id"],
            "name": encounter["name"],
            "status": encounter["status"],
            "round": encounter["round"],
            "turn_index": encounter["turn_index"],
            "active": _active_combatant_info(active) if active else None,
            "order": [_active_combatant_info(c) for c in order],
            "conditions": json.loads(encounter["conditions_json"]),
        }
    )



# ---------------------------------------------------------------------------
# Encounter rewards
# ---------------------------------------------------------------------------


@csrf_exempt
def award_rewards(request, id, enc_id):
    bad = require_method(request, "POST")
    if bad:
        return bad

    actor, err = require_actor(request, "dm")
    if err is not None:
        return err

    body = parse_json(request)
    if body is None:
        return bad_request("invalid request")
    try:
        xp = int(body["xp"])
        loot = body["loot"]
        if not isinstance(loot, list):
            raise ValueError
        for item in loot:
            if not isinstance(item, dict):
                raise ValueError
            if not isinstance(item.get("slug"), str) or not isinstance(item.get("quantity"), int):
                raise ValueError
            if item["quantity"] <= 0:
                raise ValueError
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid request")

    with db_conn() as conn:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (id,)
        ).fetchone()
        if campaign is None:
            return not_found("campaign not found")

        if actor["username"] != campaign["owner"]:
            return forbidden()

        encounter = conn.execute(
            "SELECT id, campaign_id FROM encounters WHERE id = ?", (enc_id,)
        ).fetchone()
        if encounter is None or encounter["campaign_id"] != id:
            return not_found("encounter not found")

        existing = conn.execute(
            "SELECT 1 FROM encounter_rewards WHERE encounter_id = ?", (enc_id,)
        ).fetchone()
        if existing is not None:
            return conflict("rewards already awarded")

        conn.execute(
            "INSERT INTO encounter_rewards (encounter_id, xp, loot_json) VALUES (?, ?, ?)",
            (enc_id, xp, json.dumps(loot)),
        )

    return JsonResponse({"encounter_id": enc_id, "xp": xp, "loot": loot})


@csrf_exempt
def close_encounter(request, id, enc_id):
    bad = require_method(request, "POST")
    if bad:
        return bad

    actor, err = require_actor(request, "dm")
    if err is not None:
        return err

    with db_conn() as conn:
        campaign = conn.execute(
            "SELECT id, owner FROM play_campaigns WHERE id = ?", (id,)
        ).fetchone()
        if campaign is None:
            return not_found("campaign not found")

        if actor["username"] != campaign["owner"]:
            return forbidden()

        encounter = conn.execute(
            "SELECT id, campaign_id, status FROM encounters WHERE id = ?", (enc_id,)
        ).fetchone()
        if encounter is None or encounter["campaign_id"] != id:
            return not_found("encounter not found")

        conn.execute(
            "UPDATE encounters SET status = 'closed' WHERE id = ?",
            (enc_id,),
        )

        reward = conn.execute(
            "SELECT xp FROM encounter_rewards WHERE encounter_id = ?", (enc_id,)
        ).fetchone()
        xp_awarded = reward["xp"] if reward is not None else 0

    return JsonResponse({"id": enc_id, "status": "closed", "xp_awarded": xp_awarded})


@csrf_exempt
def end_encounter(request, id, enc_id):
    bad = require_method(request, "POST")
    if bad:
        return bad

    actor, err = require_actor(request, "dm")
    if err is not None:
        return err

    with db_conn() as conn:
        campaign = conn.execute(
            "SELECT id, owner, status, phase, current_actor, saved_actor FROM play_campaigns WHERE id = ?",
            (id,),
        ).fetchone()
        if campaign is None:
            return not_found("campaign not found")

        if actor["username"] != campaign["owner"]:
            return forbidden()

        encounter = conn.execute(
            "SELECT id, campaign_id, status FROM encounters WHERE id = ?", (enc_id,)
        ).fetchone()
        if encounter is None or encounter["campaign_id"] != id:
            return not_found("encounter not found")

        if campaign["phase"] != "combat":
            return conflict("campaign not in combat")

        conn.execute(
            "UPDATE encounters SET status = 'closed' WHERE id = ? AND status = 'active'",
            (enc_id,),
        )

        restored_actor = campaign["owner"]
        conn.execute(
            "UPDATE play_campaigns SET phase = ?, current_actor = ?, saved_actor = ? WHERE id = ?",
            ("exploration", restored_actor, None, id),
        )

    return JsonResponse(
        {
            "campaign_id": id,
            "status": campaign["status"],
            "phase": "exploration",
            "current_actor": restored_actor,
        }
    )



