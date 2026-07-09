#!/usr/bin/env python3
"""D&D REST API server (Python 3.14 stdlib only)."""

import json
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DICE_RE = re.compile(r"^(\d+)d(\d+)([+-]\d+)?$")

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

# Per-character thresholds by level.
LEVEL_THRESHOLDS = {
    3: {"easy": 75, "medium": 150, "hard": 225, "deadly": 400},
}


class HttpError(Exception):
    def __init__(self, status, message="bad request"):
        self.status = status
        self.message = message


def multiplier_for(count):
    if count <= 0:
        return 1
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


def dice_stats(body):
    expr = body.get("expression")
    if not isinstance(expr, str):
        raise HttpError(400, "invalid expression")
    m = DICE_RE.match(expr.strip())
    if not m:
        raise HttpError(400, "invalid expression")
    count = int(m.group(1))
    sides = int(m.group(2))
    modifier = int(m.group(3)) if m.group(3) else 0
    if count <= 0 or sides <= 0:
        raise HttpError(400, "count and sides must be positive")
    minimum = count * 1 + modifier
    maximum = count * sides + modifier
    average = (minimum + maximum) / 2
    if average == int(average):
        average = int(average)
    return {
        "dice_count": count,
        "sides": sides,
        "modifier": modifier,
        "min": minimum,
        "max": maximum,
        "average": average,
    }


def ability_check(body):
    try:
        roll = body["roll"]
        modifier = body["modifier"]
        dc = body["dc"]
    except (KeyError, TypeError):
        raise HttpError(400, "missing fields")
    if not all(isinstance(v, int) and not isinstance(v, bool) for v in (roll, modifier, dc)):
        raise HttpError(400, "fields must be integers")
    total = roll + modifier
    return {
        "total": total,
        "success": total >= dc,
        "margin": total - dc,
    }


def adjusted_xp(body):
    party = body.get("party")
    monsters = body.get("monsters")
    if not isinstance(party, list) or not isinstance(monsters, list):
        raise HttpError(400, "party and monsters required")

    base_xp = 0
    monster_count = 0
    for mon in monsters:
        if not isinstance(mon, dict):
            raise HttpError(400, "invalid monster")
        cr = mon.get("cr")
        count = mon.get("count")
        if cr not in CR_XP:
            raise HttpError(400, "unsupported CR: %s" % (cr,))
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            raise HttpError(400, "invalid monster count")
        base_xp += CR_XP[cr] * count
        monster_count += count

    multiplier = multiplier_for(monster_count)
    adjusted = base_xp * multiplier
    if adjusted == int(adjusted):
        adjusted = int(adjusted)
    if multiplier == int(multiplier):
        multiplier = int(multiplier)

    thresholds = {"easy": 0, "medium": 0, "hard": 0, "deadly": 0}
    for member in party:
        if not isinstance(member, dict):
            raise HttpError(400, "invalid party member")
        level = member.get("level")
        if level not in LEVEL_THRESHOLDS:
            raise HttpError(400, "unsupported level: %s" % (level,))
        for key, value in LEVEL_THRESHOLDS[level].items():
            thresholds[key] += value

    difficulty = "trivial"
    for key in ("easy", "medium", "hard", "deadly"):
        if adjusted >= thresholds[key]:
            difficulty = key

    return {
        "base_xp": base_xp,
        "monster_count": monster_count,
        "multiplier": multiplier,
        "adjusted_xp": adjusted,
        "difficulty": difficulty,
        "thresholds": thresholds,
    }


def initiative_order(body):
    combatants = body.get("combatants")
    if not isinstance(combatants, list):
        raise HttpError(400, "combatants required")
    entries = []
    for c in combatants:
        if not isinstance(c, dict):
            raise HttpError(400, "invalid combatant")
        name = c.get("name")
        dex = c.get("dex")
        roll = c.get("roll")
        if not isinstance(name, str):
            raise HttpError(400, "invalid name")
        if not isinstance(dex, int) or isinstance(dex, bool):
            raise HttpError(400, "invalid dex")
        if not isinstance(roll, int) or isinstance(roll, bool):
            raise HttpError(400, "invalid roll")
        entries.append((name, dex, roll))

    entries.sort(key=lambda e: (-(e[2] + e[1]), -e[1], e[0]))
    return {
        "order": [{"name": name, "score": roll + dex} for name, dex, roll in entries],
    }


ROUTES = {
    "/v1/dice/stats": dice_stats,
    "/v1/checks/ability": ability_check,
    "/v1/encounters/adjusted-xp": adjusted_xp,
    "/v1/initiative/order": initiative_order,
}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def _send(self, status, payload):
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/health":
            self._send(200, {"ok": True})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        handler = ROUTES.get(self.path)
        if handler is None:
            self._send(404, {"error": "not found"})
            return
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            body = json.loads(raw) if raw else {}
            if not isinstance(body, dict):
                raise HttpError(400, "body must be an object")
            result = handler(body)
        except HttpError as e:
            self._send(e.status, {"error": e.message})
            return
        except (json.JSONDecodeError, ValueError):
            self._send(400, {"error": "invalid JSON"})
            return
        self._send(200, result)


def main():
    port = int(os.environ.get("PORT", "8000"))
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()
