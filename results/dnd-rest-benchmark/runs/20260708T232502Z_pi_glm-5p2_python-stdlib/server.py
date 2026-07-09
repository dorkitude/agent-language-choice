#!/usr/bin/env python3
"""D&D REST API server using only the Python standard library.

Endpoints:
  GET  /health
  POST /v1/dice/stats
  POST /v1/checks/ability
  POST /v1/encounters/adjusted-xp
  POST /v1/initiative/order
"""

import json
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# ---------------------------------------------------------------------------
# Data tables
# ---------------------------------------------------------------------------

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

# Per-level encounter thresholds (XP). First benchmark suite supports level 3.
LEVEL_THRESHOLDS = {
    3: {"easy": 75, "medium": 150, "hard": 225, "deadly": 400},
}

# <count>d<sides>[+<modifier>|-<modifier>]
DICE_EXPR_RE = re.compile(r"^(\d+)d(\d+)(?:([+-])(\d+))?$")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class ApiError(Exception):
    """Raised for any client error; mapped to an HTTP response."""

    def __init__(self, message, status=400):
        super().__init__(message)
        self.message = message
        self.status = status


def is_int(value):
    """True for genuine integers (bools are excluded)."""
    return isinstance(value, int) and not isinstance(value, bool)


def require_int(obj, key):
    if key not in obj:
        raise ApiError("missing field: {}".format(key))
    value = obj[key]
    if not is_int(value):
        raise ApiError("field {} must be an integer".format(key))
    return value


def normalize_number(value):
    """Collapse whole floats to int so JSON renders 1700 not 1700.0."""
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def multiplier_for(monster_count):
    if monster_count <= 1:
        return 1
    if monster_count == 2:
        return 1.5
    if monster_count <= 6:
        return 2
    if monster_count <= 10:
        return 2.5
    if monster_count <= 14:
        return 3
    return 4  # 15+


# ---------------------------------------------------------------------------
# Endpoint handlers
# ---------------------------------------------------------------------------


def handle_dice_stats(body):
    if not isinstance(body, dict):
        raise ApiError("request body must be an object")
    if "expression" not in body:
        raise ApiError("missing field: expression")
    expression = body["expression"]
    if not isinstance(expression, str):
        raise ApiError("expression must be a string")

    match = DICE_EXPR_RE.match(expression.strip())
    if not match:
        raise ApiError("invalid expression")

    count = int(match.group(1))
    sides = int(match.group(2))
    if count <= 0:
        raise ApiError("count must be positive")
    if sides <= 0:
        raise ApiError("sides must be positive")

    sign = match.group(3)
    if sign is None:
        modifier = 0
    else:
        modifier = int(match.group(4))
        if sign == "-":
            modifier = -modifier

    min_val = count + modifier
    max_val = count * sides + modifier
    total = min_val + max_val
    average = total // 2 if total % 2 == 0 else total / 2

    return {
        "dice_count": count,
        "sides": sides,
        "modifier": modifier,
        "min": min_val,
        "max": max_val,
        "average": average,
    }


def handle_ability_check(body):
    if not isinstance(body, dict):
        raise ApiError("request body must be an object")
    roll = require_int(body, "roll")
    modifier = require_int(body, "modifier")
    dc = require_int(body, "dc")

    total = roll + modifier
    return {
        "total": total,
        "success": total >= dc,
        "margin": total - dc,
    }


def handle_adjusted_xp(body):
    if not isinstance(body, dict):
        raise ApiError("request body must be an object")
    if "party" not in body:
        raise ApiError("missing field: party")
    if "monsters" not in body:
        raise ApiError("missing field: monsters")
    party = body["party"]
    monsters = body["monsters"]
    if not isinstance(party, list):
        raise ApiError("party must be a list")
    if not isinstance(monsters, list):
        raise ApiError("monsters must be a list")

    # Sum party thresholds across all members.
    easy = medium = hard = deadly = 0
    for member in party:
        if not isinstance(member, dict):
            raise ApiError("party member must be an object")
        level = require_int(member, "level")
        if level not in LEVEL_THRESHOLDS:
            raise ApiError("unsupported level: {}".format(level))
        thresholds = LEVEL_THRESHOLDS[level]
        easy += thresholds["easy"]
        medium += thresholds["medium"]
        hard += thresholds["hard"]
        deadly += thresholds["deadly"]

    # Base XP and total monster count.
    base_xp = 0
    monster_count = 0
    for monster in monsters:
        if not isinstance(monster, dict):
            raise ApiError("monster must be an object")
        if "cr" not in monster:
            raise ApiError("missing field: cr")
        cr = monster["cr"]
        if not isinstance(cr, str):
            raise ApiError("cr must be a string")
        if cr not in CR_XP:
            raise ApiError("unknown cr: {}".format(cr))
        count = require_int(monster, "count")
        if count <= 0:
            raise ApiError("count must be positive")
        base_xp += CR_XP[cr] * count
        monster_count += count

    multiplier = multiplier_for(monster_count)
    adjusted_xp = normalize_number(base_xp * multiplier)

    if adjusted_xp >= deadly:
        difficulty = "deadly"
    elif adjusted_xp >= hard:
        difficulty = "hard"
    elif adjusted_xp >= medium:
        difficulty = "medium"
    elif adjusted_xp >= easy:
        difficulty = "easy"
    else:
        difficulty = "trivial"

    return {
        "base_xp": base_xp,
        "monster_count": monster_count,
        "multiplier": multiplier,
        "adjusted_xp": adjusted_xp,
        "difficulty": difficulty,
        "thresholds": {
            "easy": easy,
            "medium": medium,
            "hard": hard,
            "deadly": deadly,
        },
    }


def handle_initiative_order(body):
    if not isinstance(body, dict):
        raise ApiError("request body must be an object")
    if "combatants" not in body:
        raise ApiError("missing field: combatants")
    combatants = body["combatants"]
    if not isinstance(combatants, list):
        raise ApiError("combatants must be a list")

    scored = []
    for combatant in combatants:
        if not isinstance(combatant, dict):
            raise ApiError("combatant must be an object")
        if "name" not in combatant:
            raise ApiError("missing field: name")
        name = combatant["name"]
        if not isinstance(name, str):
            raise ApiError("name must be a string")
        dex = require_int(combatant, "dex")
        roll = require_int(combatant, "roll")
        scored.append({"name": name, "dex": dex, "score": roll + dex})

    # score desc, dex desc, name asc.
    scored.sort(key=lambda c: (-c["score"], -c["dex"], c["name"]))

    return {
        "order": [{"name": c["name"], "score": c["score"]} for c in scored]
    }


# ---------------------------------------------------------------------------
# HTTP wiring
# ---------------------------------------------------------------------------

POST_ROUTES = {
    "/v1/dice/stats": handle_dice_stats,
    "/v1/checks/ability": handle_ability_check,
    "/v1/encounters/adjusted-xp": handle_adjusted_xp,
    "/v1/initiative/order": handle_initiative_order,
}


class Handler(BaseHTTPRequestHandler):
    server_version = "DnDRestAPI/1.0"
    protocol_version = "HTTP/1.1"

    def _send_json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length <= 0:
            return None
        raw = self.rfile.read(length)
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            raise ApiError("invalid JSON body")

    def do_GET(self):
        if self.path == "/health":
            self._send_json(200, {"ok": True})
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self):
        handler = POST_ROUTES.get(self.path)
        if handler is None:
            self._send_json(404, {"error": "not found"})
            return
        try:
            body = self._read_body()
            self._send_json(200, handler(body))
        except ApiError as err:
            self._send_json(err.status, {"error": err.message})
        except Exception:  # noqa: BLE001 - never leak a stack trace to clients
            self._send_json(500, {"error": "internal error"})

    def log_message(self, *args):  # silence default request logging
        pass


class Server(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


def main():
    port = int(os.environ.get("PORT", "8080"))
    server = Server(("127.0.0.1", port), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
