#!/usr/bin/env python3
"""Core D&D REST engine, built on the Python standard library only."""

import json
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# --- Static data tables ---------------------------------------------------

CR_XP = {
    "0": 10,
    "1/8": 25,
    "1/4": 50,
    "1/2": 100,
    "1": 200,
    "2": 450,
    "3": 700,
    "4": 1100,
    "5": 1800,
}

# Level -> (easy, medium, hard, deadly) per-character thresholds.
LEVEL_THRESHOLDS = {
    3: {"easy": 75, "medium": 150, "hard": 225, "deadly": 400},
}

DICE_RE = re.compile(r"^\s*(\d+)d(\d+)\s*([+-]\s*\d+)?\s*$")


def encounter_multiplier(monster_count):
    if monster_count <= 0:
        return 1
    if monster_count == 1:
        return 1
    if monster_count == 2:
        return 1.5
    if monster_count <= 6:
        return 2
    if monster_count <= 10:
        return 2.5
    if monster_count <= 14:
        return 3
    return 4


def _num(value):
    """Return an int when the value is integral, else a float."""
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


# --- Endpoint handlers ----------------------------------------------------


def handle_dice_stats(body):
    expression = body.get("expression")
    if not isinstance(expression, str):
        return 400, {"error": "invalid expression"}
    match = DICE_RE.match(expression)
    if not match:
        return 400, {"error": "invalid expression"}

    count = int(match.group(1))
    sides = int(match.group(2))
    modifier_token = match.group(3)
    modifier = int(modifier_token.replace(" ", "")) if modifier_token else 0

    if count <= 0 or sides <= 0:
        return 400, {"error": "invalid expression"}

    minimum = count * 1 + modifier
    maximum = count * sides + modifier
    average = (minimum + maximum) / 2

    return 200, {
        "dice_count": count,
        "sides": sides,
        "modifier": modifier,
        "min": minimum,
        "max": maximum,
        "average": _num(average),
    }


def handle_ability_check(body):
    try:
        roll = body["roll"]
        modifier = body["modifier"]
        dc = body["dc"]
    except (KeyError, TypeError):
        return 400, {"error": "missing field"}
    if not all(isinstance(v, (int, float)) and not isinstance(v, bool)
               for v in (roll, modifier, dc)):
        return 400, {"error": "invalid field"}

    total = roll + modifier
    return 200, {
        "total": _num(total),
        "success": total >= dc,
        "margin": _num(total - dc),
    }


def handle_adjusted_xp(body):
    party = body.get("party")
    monsters = body.get("monsters")
    if not isinstance(party, list) or not isinstance(monsters, list):
        return 400, {"error": "invalid party or monsters"}

    base_xp = 0
    monster_count = 0
    for monster in monsters:
        if not isinstance(monster, dict):
            return 400, {"error": "invalid monster"}
        cr = monster.get("cr")
        count = monster.get("count", 1)
        cr_key = str(cr)
        if cr_key not in CR_XP:
            return 400, {"error": "unsupported cr: %s" % cr}
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            return 400, {"error": "invalid count"}
        base_xp += CR_XP[cr_key] * count
        monster_count += count

    thresholds = {"easy": 0, "medium": 0, "hard": 0, "deadly": 0}
    for member in party:
        if not isinstance(member, dict):
            return 400, {"error": "invalid party member"}
        level = member.get("level")
        if level not in LEVEL_THRESHOLDS:
            return 400, {"error": "unsupported level: %s" % level}
        for key, value in LEVEL_THRESHOLDS[level].items():
            thresholds[key] += value

    multiplier = encounter_multiplier(monster_count)
    adjusted_xp = base_xp * multiplier

    difficulty = "trivial"
    for key in ("easy", "medium", "hard", "deadly"):
        if adjusted_xp >= thresholds[key]:
            difficulty = key

    return 200, {
        "base_xp": _num(base_xp),
        "monster_count": monster_count,
        "multiplier": _num(multiplier),
        "adjusted_xp": _num(adjusted_xp),
        "difficulty": difficulty,
        "thresholds": thresholds,
    }


def handle_initiative_order(body):
    combatants = body.get("combatants")
    if not isinstance(combatants, list):
        return 400, {"error": "invalid combatants"}

    scored = []
    for combatant in combatants:
        if not isinstance(combatant, dict):
            return 400, {"error": "invalid combatant"}
        name = combatant.get("name")
        dex = combatant.get("dex")
        roll = combatant.get("roll")
        if not isinstance(name, str):
            return 400, {"error": "invalid name"}
        if not all(isinstance(v, (int, float)) and not isinstance(v, bool)
                   for v in (dex, roll)):
            return 400, {"error": "invalid combatant fields"}
        scored.append({"name": name, "dex": dex, "score": roll + dex})

    scored.sort(key=lambda c: (-c["score"], -c["dex"], c["name"]))

    order = [{"name": c["name"], "score": _num(c["score"])} for c in scored]
    return 200, {"order": order}


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def ability_modifier(score):
    """floor((score - 10) / 2), flooring negative halves correctly."""
    return (score - 10) // 2


def proficiency_bonus(level):
    return (level - 1) // 4 + 2


def handle_ability_modifier(body):
    score = body.get("score")
    if not _is_int(score) or score < 1 or score > 30:
        return 400, {"error": "invalid score"}
    return 200, {"score": score, "modifier": ability_modifier(score)}


def handle_proficiency(body):
    level = body.get("level")
    if not _is_int(level) or level < 1 or level > 20:
        return 400, {"error": "invalid level"}
    return 200, {"level": level, "proficiency_bonus": proficiency_bonus(level)}


def handle_derived_stats(body):
    level = body.get("level")
    if not _is_int(level) or level < 1 or level > 20:
        return 400, {"error": "invalid level"}

    abilities = body.get("abilities")
    if not isinstance(abilities, dict):
        return 400, {"error": "invalid abilities"}

    modifiers = {}
    for key in ("str", "dex", "con", "int", "wis", "cha"):
        score = abilities.get(key)
        if not _is_int(score) or score < 1 or score > 30:
            return 400, {"error": "invalid ability: %s" % key}
        modifiers[key] = ability_modifier(score)

    armor = body.get("armor")
    if not isinstance(armor, dict):
        return 400, {"error": "invalid armor"}
    base = armor.get("base")
    dex_cap = armor.get("dex_cap")
    shield = armor.get("shield")
    if not _is_int(base):
        return 400, {"error": "invalid armor base"}
    if not _is_int(dex_cap):
        return 400, {"error": "invalid armor dex_cap"}
    if not isinstance(shield, bool):
        return 400, {"error": "invalid armor shield"}

    shield_bonus = 2 if shield else 0
    hp_max = level * (6 + modifiers["con"])
    armor_class = base + min(modifiers["dex"], dex_cap) + shield_bonus

    return 200, {
        "level": level,
        "proficiency_bonus": proficiency_bonus(level),
        "hp_max": hp_max,
        "armor_class": armor_class,
        "modifiers": modifiers,
    }


# --- Stateful combat ------------------------------------------------------

COMBAT_SESSIONS = {}


def _session_view(session):
    """Build the create/advance response view for a session."""
    order = [{"name": c["name"], "score": _num(c["score"])}
             for c in session["order"]]
    active = order[session["turn_index"]]
    return {
        "id": session["id"],
        "round": session["round"],
        "turn_index": session["turn_index"],
        "active": active,
        "order": order,
    }


def handle_create_combat_session(body):
    session_id = body.get("id")
    if not isinstance(session_id, str) or not session_id:
        return 400, {"error": "invalid id"}
    if session_id in COMBAT_SESSIONS:
        return 400, {"error": "session already exists"}

    combatants = body.get("combatants")
    if not isinstance(combatants, list) or not combatants:
        return 400, {"error": "invalid combatants"}

    scored = []
    for combatant in combatants:
        if not isinstance(combatant, dict):
            return 400, {"error": "invalid combatant"}
        name = combatant.get("name")
        dex = combatant.get("dex")
        roll = combatant.get("roll")
        if not isinstance(name, str) or not name:
            return 400, {"error": "invalid name"}
        if not all(isinstance(v, (int, float)) and not isinstance(v, bool)
                   for v in (dex, roll)):
            return 400, {"error": "invalid combatant fields"}
        scored.append({"name": name, "dex": dex, "score": roll + dex})

    scored.sort(key=lambda c: (-c["score"], -c["dex"], c["name"]))

    session = {
        "id": session_id,
        "order": scored,
        "round": 1,
        "turn_index": 0,
        "conditions": {c["name"]: [] for c in scored},
    }
    COMBAT_SESSIONS[session_id] = session
    return 200, _session_view(session)


def handle_add_condition(session_id, body):
    session = COMBAT_SESSIONS.get(session_id)
    if session is None:
        return 404, {"error": "unknown session"}

    target = body.get("target")
    condition = body.get("condition")
    duration = body.get("duration_rounds")
    if not isinstance(target, str) or target not in session["conditions"]:
        return 400, {"error": "invalid target"}
    if not isinstance(condition, str) or not condition:
        return 400, {"error": "invalid condition"}
    if not _is_int(duration) or duration <= 0:
        return 400, {"error": "invalid duration_rounds"}

    session["conditions"][target].append(
        {"condition": condition, "remaining_rounds": duration})
    return 200, {
        "target": target,
        "conditions": list(session["conditions"][target]),
    }


def handle_advance_turn(session_id, body):
    session = COMBAT_SESSIONS.get(session_id)
    if session is None:
        return 404, {"error": "unknown session"}

    count = len(session["order"])
    session["turn_index"] += 1
    if session["turn_index"] >= count:
        session["turn_index"] = 0
        session["round"] += 1

    active_name = session["order"][session["turn_index"]]["name"]
    active_conditions = session["conditions"][active_name]
    remaining = []
    for entry in active_conditions:
        entry["remaining_rounds"] -= 1
        if entry["remaining_rounds"] > 0:
            remaining.append(entry)
    session["conditions"][active_name] = remaining

    view = _session_view(session)
    conditions = {name: list(entries)
                  for name, entries in session["conditions"].items()}
    return 200, {
        "id": view["id"],
        "round": view["round"],
        "turn_index": view["turn_index"],
        "active": view["active"],
        "conditions": conditions,
    }


COMBAT_CONDITIONS_RE = re.compile(r"^/v1/combat/sessions/([^/]+)/conditions$")
COMBAT_ADVANCE_RE = re.compile(r"^/v1/combat/sessions/([^/]+)/advance$")


# --- HTTP plumbing --------------------------------------------------------

ROUTES = {
    "/v1/dice/stats": handle_dice_stats,
    "/v1/checks/ability": handle_ability_check,
    "/v1/encounters/adjusted-xp": handle_adjusted_xp,
    "/v1/initiative/order": handle_initiative_order,
    "/v1/characters/ability-modifier": handle_ability_modifier,
    "/v1/characters/proficiency": handle_proficiency,
    "/v1/characters/derived-stats": handle_derived_stats,
    "/v1/combat/sessions": handle_create_combat_session,
}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):  # silence default logging
        pass

    def _send_json(self, status, payload):
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/health":
            self._send_json(200, {"ok": True})
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self):
        handler = ROUTES.get(self.path)
        conditions_match = COMBAT_CONDITIONS_RE.match(self.path)
        advance_match = COMBAT_ADVANCE_RE.match(self.path)
        if handler is None and conditions_match is None and advance_match is None:
            self._send_json(404, {"error": "not found"})
            return

        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            body = json.loads(raw) if raw else {}
        except (ValueError, UnicodeDecodeError):
            self._send_json(400, {"error": "invalid json"})
            return
        if not isinstance(body, dict):
            self._send_json(400, {"error": "invalid json body"})
            return

        try:
            if conditions_match is not None:
                status, payload = handle_add_condition(
                    conditions_match.group(1), body)
            elif advance_match is not None:
                status, payload = handle_advance_turn(
                    advance_match.group(1), body)
            else:
                status, payload = handler(body)
        except Exception:
            self._send_json(400, {"error": "bad request"})
            return
        self._send_json(status, payload)


def main():
    port = int(os.environ.get("PORT", "8000"))
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()
