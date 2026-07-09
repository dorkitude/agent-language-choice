#!/usr/bin/env python3
import json
import os
import re
from http.server import BaseHTTPRequestHandler, HTTPServer


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


class BadRequest(Exception):
    pass


def require_int(value, name):
    if type(value) is not int:
        raise BadRequest(f"{name} must be an integer")
    return value


def clean_number(value):
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def dice_stats(body):
    expression = body.get("expression")
    if not isinstance(expression, str):
        raise BadRequest("expression must be a string")

    match = DICE_RE.match(expression)
    if not match:
        raise BadRequest("invalid dice expression")

    count = int(match.group(1))
    sides = int(match.group(2))
    if count <= 0 or sides <= 0:
        raise BadRequest("count and sides must be positive")

    modifier = int(match.group(4) or "0")
    if match.group(3) == "-":
        modifier = -modifier

    minimum = count + modifier
    maximum = count * sides + modifier
    average = count * (sides + 1) / 2 + modifier

    return {
        "dice_count": count,
        "sides": sides,
        "modifier": modifier,
        "min": minimum,
        "max": maximum,
        "average": clean_number(average),
    }


def ability_check(body):
    roll = require_int(body.get("roll"), "roll")
    modifier = require_int(body.get("modifier"), "modifier")
    dc = require_int(body.get("dc"), "dc")
    total = roll + modifier
    return {"total": total, "success": total >= dc, "margin": total - dc}


def monster_multiplier(monster_count):
    if monster_count <= 0:
        raise BadRequest("monster count must be positive")
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


def encounter_xp(body):
    party = body.get("party")
    monsters = body.get("monsters")
    if not isinstance(party, list) or not party:
        raise BadRequest("party must be a non-empty list")
    if not isinstance(monsters, list) or not monsters:
        raise BadRequest("monsters must be a non-empty list")

    thresholds = {"easy": 0, "medium": 0, "hard": 0, "deadly": 0}
    for member in party:
        if not isinstance(member, dict):
            raise BadRequest("party members must be objects")
        level = require_int(member.get("level"), "level")
        if level not in LEVEL_THRESHOLDS:
            raise BadRequest("unsupported level")
        for name, amount in LEVEL_THRESHOLDS[level].items():
            thresholds[name] += amount

    base_xp = 0
    monster_count = 0
    for monster in monsters:
        if not isinstance(monster, dict):
            raise BadRequest("monsters must be objects")
        cr = monster.get("cr")
        count = require_int(monster.get("count"), "count")
        if cr not in MONSTER_XP:
            raise BadRequest("unsupported challenge rating")
        if count <= 0:
            raise BadRequest("monster count must be positive")
        base_xp += MONSTER_XP[cr] * count
        monster_count += count

    multiplier = monster_multiplier(monster_count)
    adjusted_xp = base_xp * multiplier

    difficulty = "trivial"
    for name in ("easy", "medium", "hard", "deadly"):
        if adjusted_xp >= thresholds[name]:
            difficulty = name

    return {
        "base_xp": base_xp,
        "monster_count": monster_count,
        "multiplier": clean_number(multiplier),
        "adjusted_xp": clean_number(adjusted_xp),
        "difficulty": difficulty,
        "thresholds": thresholds,
    }


def initiative_order(body):
    combatants = body.get("combatants")
    if not isinstance(combatants, list):
        raise BadRequest("combatants must be a list")

    rows = []
    for combatant in combatants:
        if not isinstance(combatant, dict):
            raise BadRequest("combatants must be objects")
        name = combatant.get("name")
        if not isinstance(name, str):
            raise BadRequest("name must be a string")
        dex = require_int(combatant.get("dex"), "dex")
        roll = require_int(combatant.get("roll"), "roll")
        rows.append({"name": name, "dex": dex, "score": roll + dex})

    rows.sort(key=lambda item: (-item["score"], -item["dex"], item["name"]))
    return {"order": [{"name": item["name"], "score": item["score"]} for item in rows]}


ROUTES = {
    "/v1/dice/stats": dice_stats,
    "/v1/checks/ability": ability_check,
    "/v1/encounters/adjusted-xp": encounter_xp,
    "/v1/initiative/order": initiative_order,
}


class Handler(BaseHTTPRequestHandler):
    server_version = "DndRest/1.0"

    def log_message(self, format, *args):
        return

    def send_json(self, status, payload):
        data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/health":
            self.send_json(200, {"ok": True})
        else:
            self.send_json(404, {"error": "not found"})

    def do_POST(self):
        handler = ROUTES.get(self.path)
        if handler is None:
            self.send_json(404, {"error": "not found"})
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(body, dict):
                raise BadRequest("request body must be an object")
            self.send_json(200, handler(body))
        except (BadRequest, json.JSONDecodeError, UnicodeDecodeError, ValueError):
            self.send_json(400, {"error": "bad request"})


def main():
    port = int(os.environ["PORT"])
    server = HTTPServer(("127.0.0.1", port), Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()
