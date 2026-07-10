#!/usr/bin/env python3
import json
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock
from urllib.parse import unquote, urlparse


DICE_RE = re.compile(r"^([0-9]+)d([0-9]+)(?:([+-])([0-9]+))?$")

MONSTER_XP = {
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

LEVEL_THRESHOLDS = {
    3: {"easy": 75, "medium": 150, "hard": 225, "deadly": 400},
}

ABILITY_NAMES = ("str", "dex", "con", "int", "wis", "cha")


class BadRequest(Exception):
    pass


class NotFound(Exception):
    pass


COMBAT_SESSIONS = {}
COMBAT_LOCK = Lock()


def require_int(value, name):
    if type(value) is not int:
        raise BadRequest(f"{name} must be an integer")
    return value


def require_range(value, name, minimum, maximum):
    value = require_int(value, name)
    if value < minimum or value > maximum:
        raise BadRequest(f"{name} must be between {minimum} and {maximum}")
    return value


def ability_modifier_for_score(score):
    score = require_range(score, "score", 1, 30)
    return (score - 10) // 2


def proficiency_bonus_for_level(level):
    level = require_range(level, "level", 1, 20)
    return 2 + (level - 1) // 4


def dice_stats(payload):
    expression = payload.get("expression")
    if type(expression) is not str:
        raise BadRequest("expression must be a string")

    match = DICE_RE.fullmatch(expression)
    if not match:
        raise BadRequest("invalid dice expression")

    count = int(match.group(1))
    sides = int(match.group(2))
    if count <= 0 or sides <= 0:
        raise BadRequest("dice count and sides must be positive")

    modifier = int(match.group(4) or "0")
    if match.group(3) == "-":
        modifier = -modifier

    minimum = count + modifier
    maximum = count * sides + modifier
    average = count * (sides + 1) / 2 + modifier
    if average.is_integer():
        average = int(average)

    return {
        "dice_count": count,
        "sides": sides,
        "modifier": modifier,
        "min": minimum,
        "max": maximum,
        "average": average,
    }


def ability_check(payload):
    roll = require_int(payload.get("roll"), "roll")
    modifier = require_int(payload.get("modifier"), "modifier")
    dc = require_int(payload.get("dc"), "dc")
    total = roll + modifier
    return {"total": total, "success": total >= dc, "margin": total - dc}


def monster_multiplier(count):
    if count <= 0:
        raise BadRequest("monster count must be positive")
    if count == 1:
        return 1
    if count == 2:
        return 1.5
    if count <= 6:
        return 2
    if count <= 10:
        return 2.5
    if count <= 14:
        return 3
    return 4


def encounter_xp(payload):
    party = payload.get("party")
    monsters = payload.get("monsters")
    if type(party) is not list or type(monsters) is not list:
        raise BadRequest("party and monsters must be arrays")

    thresholds = {"easy": 0, "medium": 0, "hard": 0, "deadly": 0}
    for member in party:
        if type(member) is not dict:
            raise BadRequest("party members must be objects")
        level = require_int(member.get("level"), "level")
        if level not in LEVEL_THRESHOLDS:
            raise BadRequest("unsupported level")
        for key, value in LEVEL_THRESHOLDS[level].items():
            thresholds[key] += value

    base_xp = 0
    total_monsters = 0
    for monster in monsters:
        if type(monster) is not dict:
            raise BadRequest("monsters must be objects")
        cr = monster.get("cr")
        count = require_int(monster.get("count"), "count")
        if cr not in MONSTER_XP:
            raise BadRequest("unsupported challenge rating")
        if count <= 0:
            raise BadRequest("monster count must be positive")
        base_xp += MONSTER_XP[cr] * count
        total_monsters += count

    multiplier = monster_multiplier(total_monsters)
    adjusted_xp = base_xp * multiplier
    if isinstance(adjusted_xp, float) and adjusted_xp.is_integer():
        adjusted_xp = int(adjusted_xp)

    difficulty = "trivial"
    for name in ("easy", "medium", "hard", "deadly"):
        if adjusted_xp >= thresholds[name]:
            difficulty = name

    return {
        "base_xp": base_xp,
        "monster_count": total_monsters,
        "multiplier": multiplier,
        "adjusted_xp": adjusted_xp,
        "difficulty": difficulty,
        "thresholds": thresholds,
    }


def initiative_order(payload):
    entries = combat_order_entries(payload)
    return {"order": [{"name": item["name"], "score": item["score"]} for item in entries]}


def combat_order_entries(payload, allow_empty=True):
    combatants = payload.get("combatants")
    if type(combatants) is not list:
        raise BadRequest("combatants must be an array")
    if not allow_empty and not combatants:
        raise BadRequest("combatants must not be empty")

    entries = []
    for combatant in combatants:
        if type(combatant) is not dict:
            raise BadRequest("combatants must be objects")
        name = combatant.get("name")
        if type(name) is not str:
            raise BadRequest("name must be a string")
        dex = require_int(combatant.get("dex"), "dex")
        roll = require_int(combatant.get("roll"), "roll")
        score = roll + dex
        entries.append({"name": name, "dex": dex, "score": score})

    entries.sort(key=lambda item: (-item["score"], -item["dex"], item["name"]))
    return entries


def character_ability_modifier(payload):
    score = require_range(payload.get("score"), "score", 1, 30)
    return {"score": score, "modifier": ability_modifier_for_score(score)}


def character_proficiency(payload):
    level = require_range(payload.get("level"), "level", 1, 20)
    return {"level": level, "proficiency_bonus": proficiency_bonus_for_level(level)}


def character_derived_stats(payload):
    level = require_range(payload.get("level"), "level", 1, 20)
    abilities = payload.get("abilities")
    armor = payload.get("armor")
    if type(abilities) is not dict:
        raise BadRequest("abilities must be an object")
    if type(armor) is not dict:
        raise BadRequest("armor must be an object")

    modifiers = {}
    for name in ABILITY_NAMES:
        modifiers[name] = ability_modifier_for_score(abilities.get(name))

    armor_base = require_int(armor.get("base"), "base")
    shield = armor.get("shield")
    if type(shield) is not bool:
        raise BadRequest("shield must be a boolean")
    dex_cap = require_int(armor.get("dex_cap"), "dex_cap")

    shield_bonus = 2 if shield else 0
    return {
        "level": level,
        "proficiency_bonus": proficiency_bonus_for_level(level),
        "hp_max": level * (6 + modifiers["con"]),
        "armor_class": armor_base + min(modifiers["dex"], dex_cap) + shield_bonus,
        "modifiers": modifiers,
    }


def public_combatant(combatant):
    return {"name": combatant["name"], "score": combatant["score"]}


def session_response(session):
    active = session["order"][session["turn_index"]]
    return {
        "id": session["id"],
        "round": session["round"],
        "turn_index": session["turn_index"],
        "active": public_combatant(active),
        "order": [public_combatant(item) for item in session["order"]],
    }


def conditions_response(session):
    conditions = {}
    for name, items in session["conditions"].items():
        conditions[name] = [
            {"condition": item["condition"], "remaining_rounds": item["remaining_rounds"]}
            for item in items
        ]
    return conditions


def create_combat_session(payload):
    session_id = payload.get("id")
    if type(session_id) is not str:
        raise BadRequest("id must be a string")

    order = combat_order_entries(payload, allow_empty=False)
    with COMBAT_LOCK:
        if session_id in COMBAT_SESSIONS:
            raise BadRequest("session id already exists")
        session = {
            "id": session_id,
            "round": 1,
            "turn_index": 0,
            "order": order,
            "conditions": {},
        }
        COMBAT_SESSIONS[session_id] = session
        return session_response(session)


def combat_session_by_id(session_id):
    session = COMBAT_SESSIONS.get(session_id)
    if session is None:
        raise NotFound("unknown session")
    return session


def add_condition(session_id, payload):
    target = payload.get("target")
    condition = payload.get("condition")
    duration_rounds = require_int(payload.get("duration_rounds"), "duration_rounds")
    if type(target) is not str:
        raise BadRequest("target must be a string")
    if type(condition) is not str:
        raise BadRequest("condition must be a string")
    if duration_rounds <= 0:
        raise BadRequest("duration_rounds must be positive")

    with COMBAT_LOCK:
        session = combat_session_by_id(session_id)
        names = {combatant["name"] for combatant in session["order"]}
        if target not in names:
            raise BadRequest("target must be a combatant")
        target_conditions = session["conditions"].setdefault(target, [])
        target_conditions.append({"condition": condition, "remaining_rounds": duration_rounds})
        return {
            "target": target,
            "conditions": [
                {"condition": item["condition"], "remaining_rounds": item["remaining_rounds"]}
                for item in target_conditions
            ],
        }


def advance_combat_session(session_id, payload):
    if payload:
        raise BadRequest("advance does not accept a request body")

    with COMBAT_LOCK:
        session = combat_session_by_id(session_id)
        next_index = session["turn_index"] + 1
        if next_index == len(session["order"]):
            next_index = 0
            session["round"] += 1
        session["turn_index"] = next_index

        active_name = session["order"][next_index]["name"]
        active_conditions = session["conditions"].get(active_name, [])
        remaining = []
        for item in active_conditions:
            updated = item["remaining_rounds"] - 1
            if updated > 0:
                remaining.append({"condition": item["condition"], "remaining_rounds": updated})
        if active_name in session["conditions"]:
            session["conditions"][active_name] = remaining

        active = session["order"][session["turn_index"]]
        return {
            "id": session["id"],
            "round": session["round"],
            "turn_index": session["turn_index"],
            "active": public_combatant(active),
            "conditions": conditions_response(session),
        }


POST_ROUTES = {
    "/v1/dice/stats": dice_stats,
    "/v1/checks/ability": ability_check,
    "/v1/encounters/adjusted-xp": encounter_xp,
    "/v1/initiative/order": initiative_order,
    "/v1/characters/ability-modifier": character_ability_modifier,
    "/v1/characters/proficiency": character_proficiency,
    "/v1/characters/derived-stats": character_derived_stats,
    "/v1/combat/sessions": create_combat_session,
}

COMBAT_CONDITIONS_RE = re.compile(r"^/v1/combat/sessions/([^/]+)/conditions$")
COMBAT_ADVANCE_RE = re.compile(r"^/v1/combat/sessions/([^/]+)/advance$")


class Handler(BaseHTTPRequestHandler):
    server_version = "DndRest/1.0"

    def log_message(self, format, *args):
        return

    def send_json(self, status, payload):
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self.send_json(200, {"ok": True})
        else:
            self.send_json(404, {"error": "not found"})

    def do_POST(self):
        try:
            path = urlparse(self.path).path
            length = int(self.headers.get("Content-Length", "0"))
            raw_body = self.rfile.read(length)
            payload = json.loads(raw_body.decode("utf-8")) if raw_body else {}
            if type(payload) is not dict:
                raise BadRequest("request body must be an object")

            route = POST_ROUTES.get(path)
            if route is not None:
                response = route(payload)
            else:
                match = COMBAT_CONDITIONS_RE.fullmatch(path)
                if match:
                    response = add_condition(unquote(match.group(1)), payload)
                else:
                    match = COMBAT_ADVANCE_RE.fullmatch(path)
                    if match:
                        response = advance_combat_session(unquote(match.group(1)), payload)
                    else:
                        raise NotFound("route not found")
        except (BadRequest, UnicodeDecodeError, json.JSONDecodeError, ValueError):
            self.send_json(400, {"error": "bad request"})
            return
        except NotFound:
            self.send_json(404, {"error": "not found"})
            return

        self.send_json(200, response)


def main():
    port = int(os.environ.get("PORT", "8000"))
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()
