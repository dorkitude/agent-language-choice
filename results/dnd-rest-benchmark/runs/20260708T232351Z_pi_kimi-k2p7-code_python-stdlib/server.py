#!/usr/bin/env python3
import json
import os
import re
from http.server import BaseHTTPRequestHandler, HTTPServer

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

LEVEL_THRESHOLDS = {
    3: {"easy": 75, "medium": 150, "hard": 225, "deadly": 400},
}

DICE_RE = re.compile(r"^(\d+)d(\d+)([+-]\d+)?$")


def multiplier_for(count):
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


def parse_dice(expression):
    m = DICE_RE.match(expression.replace(" ", ""))
    if not m:
        return None
    count = int(m.group(1))
    sides = int(m.group(2))
    modifier = int(m.group(3)) if m.group(3) else 0
    if count <= 0 or sides <= 0:
        return None
    min_val = count + modifier
    max_val = count * sides + modifier
    return {
        "dice_count": count,
        "sides": sides,
        "modifier": modifier,
        "min": min_val,
        "max": max_val,
        "average": (min_val + max_val) // 2,
    }


def json_body(handler):
    length = int(handler.headers.get("Content-Length", 0))
    if length == 0:
        return None
    try:
        return json.loads(handler.rfile.read(length).decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None


def send_json(handler, status, body):
    data = json.dumps(body).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def handle_dice_stats(handler):
    body = json_body(handler)
    if not isinstance(body, dict) or "expression" not in body:
        send_json(handler, 400, {"error": "missing expression"})
        return
    result = parse_dice(body["expression"])
    if result is None:
        send_json(handler, 400, {"error": "invalid expression"})
        return
    send_json(handler, 200, result)


def handle_ability_check(handler):
    body = json_body(handler)
    if not isinstance(body, dict):
        send_json(handler, 400, {"error": "invalid body"})
        return
    try:
        roll = int(body["roll"])
        modifier = int(body["modifier"])
        dc = int(body["dc"])
    except (KeyError, TypeError, ValueError):
        send_json(handler, 400, {"error": "invalid fields"})
        return
    total = roll + modifier
    send_json(handler, 200, {
        "total": total,
        "success": total >= dc,
        "margin": total - dc,
    })


def handle_adjusted_xp(handler):
    body = json_body(handler)
    if not isinstance(body, dict):
        send_json(handler, 400, {"error": "invalid body"})
        return
    party = body.get("party", [])
    monsters = body.get("monsters", [])
    if not isinstance(party, list) or not isinstance(monsters, list):
        send_json(handler, 400, {"error": "invalid party or monsters"})
        return

    thresholds = {"easy": 0, "medium": 0, "hard": 0, "deadly": 0}
    for member in party:
        if not isinstance(member, dict):
            send_json(handler, 400, {"error": "invalid party member"})
            return
        level = member.get("level")
        t = LEVEL_THRESHOLDS.get(level)
        if not t:
            send_json(handler, 400, {"error": f"unsupported level {level}"})
            return
        for key in thresholds:
            thresholds[key] += t[key]

    base_xp = 0
    monster_count = 0
    for monster in monsters:
        if not isinstance(monster, dict):
            send_json(handler, 400, {"error": "invalid monster"})
            return
        cr = monster.get("cr")
        count = monster.get("count")
        if cr not in CR_XP or not isinstance(count, int) or count <= 0:
            send_json(handler, 400, {"error": "invalid monster entry"})
            return
        base_xp += CR_XP[cr] * count
        monster_count += count

    multiplier = multiplier_for(monster_count)
    adjusted_xp = int(base_xp * multiplier)

    if adjusted_xp >= thresholds["deadly"]:
        difficulty = "deadly"
    elif adjusted_xp >= thresholds["hard"]:
        difficulty = "hard"
    elif adjusted_xp >= thresholds["medium"]:
        difficulty = "medium"
    elif adjusted_xp >= thresholds["easy"]:
        difficulty = "easy"
    else:
        difficulty = "trivial"

    send_json(handler, 200, {
        "base_xp": base_xp,
        "monster_count": monster_count,
        "multiplier": multiplier,
        "adjusted_xp": adjusted_xp,
        "difficulty": difficulty,
        "thresholds": thresholds,
    })


def handle_initiative(handler):
    body = json_body(handler)
    if not isinstance(body, dict) or not isinstance(body.get("combatants"), list):
        send_json(handler, 400, {"error": "invalid combatants"})
        return
    order = []
    for c in body["combatants"]:
        if not isinstance(c, dict):
            send_json(handler, 400, {"error": "invalid combatant"})
            return
        try:
            name = c["name"]
            dex = int(c["dex"])
            roll = int(c["roll"])
        except (KeyError, TypeError, ValueError):
            send_json(handler, 400, {"error": "invalid combatant fields"})
            return
        order.append({"name": name, "score": roll + dex, "dex": dex})
    order.sort(key=lambda x: (-x["score"], -x["dex"], x["name"]))
    send_json(handler, 200, {
        "order": [{"name": c["name"], "score": c["score"]} for c in order]
    })


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        if self.path == "/health":
            send_json(self, 200, {"ok": True})
        else:
            send_json(self, 404, {"error": "not found"})

    def do_POST(self):
        if self.path == "/v1/dice/stats":
            handle_dice_stats(self)
        elif self.path == "/v1/checks/ability":
            handle_ability_check(self)
        elif self.path == "/v1/encounters/adjusted-xp":
            handle_adjusted_xp(self)
        elif self.path == "/v1/initiative/order":
            handle_initiative(self)
        else:
            send_json(self, 404, {"error": "not found"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    server = HTTPServer(("127.0.0.1", port), Handler)
    print(f"Listening on 127.0.0.1:{port}")
    server.serve_forever()
