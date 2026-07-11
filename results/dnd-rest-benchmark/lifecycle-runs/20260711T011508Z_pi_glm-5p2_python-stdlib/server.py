#!/usr/bin/env python3
"""Core D&D REST engine — Python 3.14 standard library only."""
import json
import os
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, unquote

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _is_number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _numify(x):
    """Render whole floats as int so 10.0 -> 10 (matches spec examples)."""
    if isinstance(x, float) and x.is_integer():
        return int(x)
    return x


# ---------------------------------------------------------------------------
# POST /v1/dice/stats
#   grammar: <count>d<sides>[+<modifier>|-<modifier>]
# ---------------------------------------------------------------------------
_DICE_RE = re.compile(r"^(\d+)d(\d+)(?:([+-])(\d+))?$")


def dice_stats(expression):
    if not isinstance(expression, str):
        return None
    m = _DICE_RE.match(expression.strip())
    if not m:
        return None
    count, sides = int(m.group(1)), int(m.group(2))
    if count <= 0 or sides <= 0:
        return None
    modifier = int(m.group(3) + m.group(4)) if m.group(3) else 0
    lo = count + modifier
    hi = count * sides + modifier
    avg = (lo + hi) / 2
    return {
        "dice_count": count,
        "sides": sides,
        "modifier": modifier,
        "min": lo,
        "max": hi,
        "average": _numify(avg),
    }


# ---------------------------------------------------------------------------
# POST /v1/checks/ability
# ---------------------------------------------------------------------------
def ability_check(body):
    try:
        roll, modifier, dc = body["roll"], body["modifier"], body["dc"]
    except (KeyError, TypeError):
        return None
    if not (_is_number(roll) and _is_number(modifier) and _is_number(dc)):
        return None
    total = _numify(roll + modifier)
    return {
        "total": total,
        "success": total >= dc,
        "margin": _numify(total - dc),
    }


# ---------------------------------------------------------------------------
# POST /v1/encounters/adjusted-xp
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

# D&D 5e per-character XP thresholds: (easy, medium, hard, deadly).
# Level 3 matches the benchmark spec exactly; the rest is the standard table.
LEVEL_THRESHOLDS = {
    1: (25, 50, 75, 100),
    2: (50, 100, 150, 200),
    3: (75, 150, 225, 400),
    4: (125, 250, 375, 500),
    5: (250, 500, 750, 1100),
    6: (300, 600, 900, 1400),
    7: (350, 750, 1100, 1700),
    8: (450, 900, 1400, 2100),
    9: (550, 1100, 1600, 2400),
    10: (600, 1200, 1900, 2800),
    11: (800, 1600, 2400, 3700),
    12: (1000, 2000, 3000, 4500),
    13: (1100, 2200, 3400, 5100),
    14: (1250, 2500, 3800, 5700),
    15: (1400, 2800, 4300, 6400),
    16: (1600, 3200, 4800, 7200),
    17: (2000, 3900, 5900, 8800),
    18: (2100, 4200, 6300, 9500),
    19: (2400, 4700, 7200, 10900),
    20: (2800, 5700, 8500, 12700),
}


def _multiplier(monster_count):
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
    return 4


def adjusted_xp(body):
    try:
        party, monsters = body["party"], body["monsters"]
    except (KeyError, TypeError):
        return None
    if not isinstance(party, list) or not isinstance(monsters, list):
        return None

    base_xp = 0
    monster_count = 0
    for mon in monsters:
        try:
            cr, count = mon["cr"], mon["count"]
        except (KeyError, TypeError):
            return None
        if cr not in CR_XP:
            return None
        if not isinstance(count, int) or isinstance(count, bool) or count < 1:
            return None
        base_xp += CR_XP[cr] * count
        monster_count += count

    mult = _multiplier(monster_count)
    adjusted = _numify(base_xp * mult)

    easy = medium = hard = deadly = 0
    for member in party:
        try:
            level = member["level"]
        except (KeyError, TypeError):
            return None
        tier = LEVEL_THRESHOLDS.get(level)
        if tier is None:
            return None
        easy += tier[0]
        medium += tier[1]
        hard += tier[2]
        deadly += tier[3]

    if adjusted >= deadly:
        difficulty = "deadly"
    elif adjusted >= hard:
        difficulty = "hard"
    elif adjusted >= medium:
        difficulty = "medium"
    elif adjusted >= easy:
        difficulty = "easy"
    else:
        difficulty = "trivial"

    return {
        "base_xp": base_xp,
        "monster_count": monster_count,
        "multiplier": _numify(mult),
        "adjusted_xp": adjusted,
        "difficulty": difficulty,
        "thresholds": {
            "easy": easy,
            "medium": medium,
            "hard": hard,
            "deadly": deadly,
        },
    }


# ---------------------------------------------------------------------------
# POST /v1/initiative/order
# ---------------------------------------------------------------------------
def initiative_order(body):
    try:
        combatants = body["combatants"]
    except (KeyError, TypeError):
        return None
    if not isinstance(combatants, list):
        return None
    entries = []
    for c in combatants:
        try:
            name, dex, roll = c["name"], c["dex"], c["roll"]
        except (KeyError, TypeError):
            return None
        if not isinstance(name, str):
            return None
        if not isinstance(dex, int) or isinstance(dex, bool):
            return None
        if not isinstance(roll, int) or isinstance(roll, bool):
            return None
        entries.append((roll + dex, dex, name))
    # score desc, dex desc, name asc
    entries.sort(key=lambda e: (-e[0], -e[1], e[2]))
    return {"order": [{"name": e[2], "score": e[0]} for e in entries]}


# ---------------------------------------------------------------------------
# POST /v1/characters/ability-modifier
# ---------------------------------------------------------------------------
_ABILITIES = ("str", "dex", "con", "int", "wis", "cha")


def ability_modifier(score):
    """modifier = floor((score - 10) / 2); floors negative halves down."""
    return (score - 10) // 2


def ability_modifier_endpoint(body):
    try:
        score = body["score"]
    except (KeyError, TypeError):
        return None
    if not isinstance(score, int) or isinstance(score, bool):
        return None
    if score < 1 or score > 30:
        return None
    return {"score": score, "modifier": ability_modifier(score)}


# ---------------------------------------------------------------------------
# POST /v1/characters/proficiency
# ---------------------------------------------------------------------------
def proficiency_bonus(level):
    """2 + (level - 1) // 4, clamped to the standard 2-6 progression."""
    return 2 + (level - 1) // 4


def proficiency_endpoint(body):
    try:
        level = body["level"]
    except (KeyError, TypeError):
        return None
    if not isinstance(level, int) or isinstance(level, bool):
        return None
    if level < 1 or level > 20:
        return None
    return {"level": level, "proficiency_bonus": proficiency_bonus(level)}


# ---------------------------------------------------------------------------
# POST /v1/characters/derived-stats
# ---------------------------------------------------------------------------
def derived_stats(body):
    try:
        level = body["level"]
        abilities = body["abilities"]
        armor = body["armor"]
    except (KeyError, TypeError):
        return None
    if not isinstance(level, int) or isinstance(level, bool):
        return None
    if level < 1 or level > 20:
        return None
    if not isinstance(abilities, dict):
        return None
    if not isinstance(armor, dict):
        return None

    modifiers = {}
    for ab in _ABILITIES:
        score = abilities.get(ab)
        if not isinstance(score, int) or isinstance(score, bool):
            return None
        if score < 1 or score > 30:
            return None
        modifiers[ab] = ability_modifier(score)

    try:
        base = armor["base"]
        shield = armor["shield"]
        dex_cap = armor["dex_cap"]
    except (KeyError, TypeError):
        return None
    if not isinstance(base, int) or isinstance(base, bool):
        return None
    if not isinstance(shield, bool):
        return None
    if not isinstance(dex_cap, int) or isinstance(dex_cap, bool):
        return None

    dex_mod = modifiers["dex"]
    con_mod = modifiers["con"]
    hp_max = level * (6 + con_mod)
    shield_bonus = 2 if shield else 0
    armor_class = base + min(dex_mod, dex_cap) + shield_bonus

    return {
        "level": level,
        "proficiency_bonus": proficiency_bonus(level),
        "hp_max": hp_max,
        "armor_class": armor_class,
        "modifiers": modifiers,
    }


# ---------------------------------------------------------------------------
# Combat sessions (stateful, in-memory)
# ---------------------------------------------------------------------------
_SESSIONS = {}
_SESSION_LOCK = threading.Lock()

_COMBAT_SESSIONS_RE = re.compile(r"^/v1/combat/sessions$")
_COMBAT_CONDITIONS_RE = re.compile(r"^/v1/combat/sessions/([^/]+)/conditions$")
_COMBAT_ADVANCE_RE = re.compile(r"^/v1/combat/sessions/([^/]+)/advance$")


def _validate_combatants(combatants):
    """Return sorted initiative order (score desc, dex desc, name asc) or None."""
    if not isinstance(combatants, list) or not combatants:
        return None
    entries = []
    for c in combatants:
        if not isinstance(c, dict):
            return None
        try:
            name, dex, roll = c["name"], c["dex"], c["roll"]
        except (KeyError, TypeError):
            return None
        if not isinstance(name, str):
            return None
        if not isinstance(dex, int) or isinstance(dex, bool):
            return None
        if not isinstance(roll, int) or isinstance(roll, bool):
            return None
        entries.append((roll + dex, dex, name))
    entries.sort(key=lambda e: (-e[0], -e[1], e[2]))
    return [{"name": e[2], "score": e[0]} for e in entries]


def create_combat_session(body):
    """POST /v1/combat/sessions — create (or reset) a combat session."""
    if not isinstance(body, dict):
        return 400, {"error": "invalid request body"}
    sid = body.get("id")
    if not isinstance(sid, str) or not sid:
        return 400, {"error": "invalid id"}
    order = _validate_combatants(body.get("combatants"))
    if order is None:
        return 400, {"error": "invalid combatants"}
    with _SESSION_LOCK:
        _SESSIONS[sid] = {
            "id": sid,
            "round": 1,
            "turn_index": 0,
            "order": order,
            "conditions": {},
        }
    return 200, {
        "id": sid,
        "round": 1,
        "turn_index": 0,
        "active": dict(order[0]),
        "order": [dict(e) for e in order],
    }


def add_condition(sid, body):
    """POST /v1/combat/sessions/{id}/conditions — attach a condition to a combatant."""
    with _SESSION_LOCK:
        session = _SESSIONS.get(sid)
        if session is None:
            return 404, {"error": "unknown session"}
        if not isinstance(body, dict):
            return 400, {"error": "invalid request body"}
        target = body.get("target")
        condition = body.get("condition")
        duration = body.get("duration_rounds")
        names = {e["name"] for e in session["order"]}
        if not isinstance(target, str) or target not in names:
            return 400, {"error": "invalid target"}
        if not isinstance(condition, str):
            return 400, {"error": "invalid condition"}
        if not isinstance(duration, int) or isinstance(duration, bool) or duration < 1:
            return 400, {"error": "invalid duration_rounds"}
        conds = session["conditions"].setdefault(target, [])
        conds.append({"condition": condition, "remaining_rounds": duration})
        return 200, {"target": target, "conditions": [dict(c) for c in conds]}


def advance_turn(sid):
    """POST /v1/combat/sessions/{id}/advance — advance to the next combatant's turn."""
    with _SESSION_LOCK:
        session = _SESSIONS.get(sid)
        if session is None:
            return 404, {"error": "unknown session"}
        order = session["order"]
        ti = session["turn_index"] + 1
        if ti >= len(order):
            ti = 0
            session["round"] += 1
        session["turn_index"] = ti
        active = order[ti]
        active_name = active["name"]
        conds = session["conditions"].get(active_name)
        if conds:
            kept = []
            for c in conds:
                c["remaining_rounds"] -= 1
                if c["remaining_rounds"] > 0:
                    kept.append(c)
            if kept:
                session["conditions"][active_name] = kept
            else:
                session["conditions"].pop(active_name, None)
        conditions_out = {
            name: [dict(c) for c in cs]
            for name, cs in session["conditions"].items()
        }
        return 200, {
            "id": sid,
            "round": session["round"],
            "turn_index": ti,
            "active": dict(active),
            "conditions": conditions_out,
        }


# ---------------------------------------------------------------------------
# HTTP layer
# ---------------------------------------------------------------------------
class _Handler(BaseHTTPRequestHandler):
    def _send_json(self, status, payload):
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_json(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw)
        except ValueError:
            return None

    def do_GET(self):
        if urlparse(self.path).path == "/health":
            self._send_json(200, {"ok": True})
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self):
        path = urlparse(self.path).path

        # --- Combat session routes (path parameters) ---
        if _COMBAT_SESSIONS_RE.match(path):
            body = self._read_json()
            if body is None or not isinstance(body, dict):
                self._send_json(400, {"error": "invalid request body"})
                return
            status, payload = create_combat_session(body)
            self._send_json(status, payload)
            return
        m = _COMBAT_CONDITIONS_RE.match(path)
        if m:
            sid = unquote(m.group(1))
            body = self._read_json()
            if body is None or not isinstance(body, dict):
                self._send_json(400, {"error": "invalid request body"})
                return
            status, payload = add_condition(sid, body)
            self._send_json(status, payload)
            return
        m = _COMBAT_ADVANCE_RE.match(path)
        if m:
            sid = unquote(m.group(1))
            self._read_json()  # advance needs no body; discard if present
            status, payload = advance_turn(sid)
            self._send_json(status, payload)
            return

        # --- Flat dispatch for existing stateless endpoints ---
        body = self._read_json()
        if body is None or not isinstance(body, dict):
            self._send_json(400, {"error": "invalid request body"})
            return
        dispatch = {
            "/v1/dice/stats": lambda: dice_stats(body.get("expression")),
            "/v1/checks/ability": lambda: ability_check(body),
            "/v1/encounters/adjusted-xp": lambda: adjusted_xp(body),
            "/v1/initiative/order": lambda: initiative_order(body),
            "/v1/characters/ability-modifier": lambda: ability_modifier_endpoint(body),
            "/v1/characters/proficiency": lambda: proficiency_endpoint(body),
            "/v1/characters/derived-stats": lambda: derived_stats(body),
        }
        handler = dispatch.get(path)
        if handler is None:
            self._send_json(404, {"error": "not found"})
            return
        result = handler()
        if result is None:
            self._send_json(400, {"error": "bad request"})
            return
        self._send_json(200, result)

    def log_message(self, *args):
        return  # keep stderr quiet


def main():
    port = int(os.environ.get("PORT", "8000"))
    server = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()
