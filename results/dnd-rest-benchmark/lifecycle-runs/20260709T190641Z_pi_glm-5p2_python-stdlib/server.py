#!/usr/bin/env python3
"""Core D&D REST engine -- Python 3.14 standard library only."""
import json
import os
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, unquote

# ---------------------------------------------------------------------------
# Static tables
# ---------------------------------------------------------------------------

XP_TABLE = {
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

# Per-level encounter thresholds (easy/medium/hard/deadly).
LEVEL_THRESHOLDS = {
    3: {"easy": 75, "medium": 150, "hard": 225, "deadly": 400},
}

# <count>d<sides>[+<modifier>|-<modifier>]  -- count & sides must be positive.
DICE_RE = re.compile(r"^([1-9][0-9]*)d([1-9][0-9]*)(?:([+-])([0-9]+))?$")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def num(x):
    """Collapse a whole-valued float to int for clean JSON output."""
    if isinstance(x, float) and x.is_integer():
        return int(x)
    return x


def _is_int(x):
    """True for a real JSON integer (bool excluded)."""
    return isinstance(x, int) and not isinstance(x, bool)


def multiplier_for(monster_count):
    if monster_count <= 0:
        return 0
    if monster_count == 1:
        return 1
    if monster_count == 2:
        return 1.5
    if 3 <= monster_count <= 6:
        return 2
    if 7 <= monster_count <= 10:
        return 2.5
    if 11 <= monster_count <= 14:
        return 3
    return 4  # 15+


def difficulty_for(adjusted, thresholds):
    if adjusted >= thresholds["deadly"]:
        return "deadly"
    if adjusted >= thresholds["hard"]:
        return "hard"
    if adjusted >= thresholds["medium"]:
        return "medium"
    if adjusted >= thresholds["easy"]:
        return "easy"
    return "trivial"


# ---------------------------------------------------------------------------
# Endpoint logic
# ---------------------------------------------------------------------------

def dice_stats(body):
    expression = body.get("expression") if isinstance(body, dict) else None
    if not isinstance(expression, str):
        return None
    m = DICE_RE.match(expression)
    if not m:
        return None
    count = int(m.group(1))
    sides = int(m.group(2))
    if m.group(3):  # optional modifier with explicit sign
        modifier = int(m.group(4)) * (1 if m.group(3) == "+" else -1)
    else:
        modifier = 0
    lo = count + modifier
    hi = count * sides + modifier
    avg = (lo + hi) / 2
    return {
        "dice_count": count,
        "sides": sides,
        "modifier": modifier,
        "min": lo,
        "max": hi,
        "average": num(avg),
    }


def ability_check(body):
    try:
        roll = int(body["roll"])
        modifier = int(body["modifier"])
        dc = int(body["dc"])
        total = roll + modifier
        return {
            "total": total,
            "success": total >= dc,
            "margin": total - dc,
        }
    except (KeyError, TypeError, ValueError):
        return None


def adjusted_xp(body):
    try:
        party = body["party"]
        monsters = body["monsters"]

        base_xp = 0
        monster_count = 0
        for mon in monsters:
            cr = str(mon["cr"])
            count = int(mon["count"])
            if cr not in XP_TABLE:
                return None
            base_xp += XP_TABLE[cr] * count
            monster_count += count

        mult = multiplier_for(monster_count)
        adjusted = base_xp * mult

        easy = medium = hard = deadly = 0
        for member in party:
            level = int(member["level"])
            if level not in LEVEL_THRESHOLDS:
                return None
            t = LEVEL_THRESHOLDS[level]
            easy += t["easy"]
            medium += t["medium"]
            hard += t["hard"]
            deadly += t["deadly"]

        thresholds = {
            "easy": easy,
            "medium": medium,
            "hard": hard,
            "deadly": deadly,
        }
        return {
            "base_xp": base_xp,
            "monster_count": monster_count,
            "multiplier": num(mult),
            "adjusted_xp": num(adjusted),
            "difficulty": difficulty_for(adjusted, thresholds),
            "thresholds": thresholds,
        }
    except (KeyError, TypeError, ValueError):
        return None


def initiative_order(body):
    try:
        combatants = body["combatants"]
        scored = []
        for c in combatants:
            name = str(c["name"])
            dex = int(c["dex"])
            roll = int(c["roll"])
            scored.append((roll + dex, dex, name))
        # score desc, dex desc, name asc
        scored.sort(key=lambda t: (-t[0], -t[1], t[2]))
        return {"order": [{"name": n, "score": s} for (s, _d, n) in scored]}
    except (KeyError, TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Character rules
# ---------------------------------------------------------------------------

ABILITY_KEYS = ("str", "dex", "con", "int", "wis", "cha")


def ability_modifier_of(score):
    """modifier = floor((score - 10) / 2); floors negative halves correctly."""
    return (score - 10) // 2


def proficiency_bonus_of(level):
    """2 + (level-1)//4 -> 2/3/4/5/6 across the 1-4/5-8/9-12/13-16/17-20 bands."""
    return 2 + (level - 1) // 4


def ability_modifier(body):
    score = body.get("score") if isinstance(body, dict) else None
    if not _is_int(score) or not (1 <= score <= 30):
        return None
    return {"score": score, "modifier": ability_modifier_of(score)}


def proficiency(body):
    level = body.get("level") if isinstance(body, dict) else None
    if not _is_int(level) or not (1 <= level <= 20):
        return None
    return {"level": level, "proficiency_bonus": proficiency_bonus_of(level)}


def derived_stats(body):
    if not isinstance(body, dict):
        return None
    level = body.get("level")
    if not _is_int(level) or not (1 <= level <= 20):
        return None
    abilities = body.get("abilities")
    if not isinstance(abilities, dict):
        return None
    modifiers = {}
    for key in ABILITY_KEYS:
        score = abilities.get(key)
        if not _is_int(score) or not (1 <= score <= 30):
            return None
        modifiers[key] = ability_modifier_of(score)
    armor = body.get("armor")
    if not isinstance(armor, dict):
        return None
    base = armor.get("base")
    dex_cap = armor.get("dex_cap")
    if not _is_int(base) or not _is_int(dex_cap):
        return None
    shield_bonus = 2 if armor.get("shield") else 0
    hp_max = level * (6 + modifiers["con"])
    armor_class = base + min(modifiers["dex"], dex_cap) + shield_bonus
    return {
        "level": level,
        "proficiency_bonus": proficiency_bonus_of(level),
        "hp_max": hp_max,
        "armor_class": armor_class,
        "modifiers": modifiers,
    }


# ---------------------------------------------------------------------------
# Combat state (in-memory, process lifetime)
# ---------------------------------------------------------------------------

SESSIONS = {}
SESSIONS_LOCK = threading.Lock()


def _validate_combatants(combatants):
    """Return sorted [(score, dex, name), ...] or None if invalid."""
    if not isinstance(combatants, list) or not combatants:
        return None
    scored = []
    for c in combatants:
        if not isinstance(c, dict):
            return None
        name = c.get("name")
        dex = c.get("dex")
        roll = c.get("roll")
        if not isinstance(name, str) or not name:
            return None
        if not _is_int(dex) or not _is_int(roll):
            return None
        scored.append((roll + dex, dex, name))
    # score desc, dex desc, name asc
    scored.sort(key=lambda t: (-t[0], -t[1], t[2]))
    return scored


def create_session(body):
    if not isinstance(body, dict):
        return 400, None
    sid = body.get("id")
    if not isinstance(sid, str) or not sid:
        return 400, None
    scored = _validate_combatants(body.get("combatants"))
    if scored is None:
        return 400, None
    order = [{"name": n, "score": s} for (s, _d, n) in scored]
    session = {
        "id": sid,
        "round": 1,
        "turn_index": 0,
        "order": order,
        "conditions": {entry["name"]: [] for entry in order},
    }
    SESSIONS[sid] = session
    return 200, {
        "id": sid,
        "round": 1,
        "turn_index": 0,
        "active": order[0],
        "order": order,
    }


def add_condition(session, body):
    if not isinstance(body, dict):
        return 400, None
    target = body.get("target")
    condition = body.get("condition")
    duration = body.get("duration_rounds")
    if not isinstance(target, str) or not target:
        return 400, None
    if not isinstance(condition, str) or not condition:
        return 400, None
    if not _is_int(duration) or duration <= 0:
        return 400, None
    if target not in session["conditions"]:
        return 400, None
    session["conditions"][target].append(
        {"condition": condition, "remaining_rounds": duration}
    )
    return 200, {"target": target, "conditions": session["conditions"][target]}


def advance_turn(session):
    order = session["order"]
    n = len(order)
    new_index = (session["turn_index"] + 1) % n
    if new_index == 0:
        session["round"] += 1
    session["turn_index"] = new_index
    active = order[new_index]
    name = active["name"]
    conds = session["conditions"].get(name, [])
    had_conds = len(conds) > 0
    for c in conds:
        c["remaining_rounds"] -= 1
    session["conditions"][name] = [c for c in conds if c["remaining_rounds"] > 0]
    conditions_out = {}
    for entry in order:
        nm = entry["name"]
        clist = session["conditions"].get(nm, [])
        # Include a combatant if they still have conditions, or if they are the
        # active combatant whose conditions were processed (and possibly
        # expired) at the start of this turn -- so an expired condition still
        # surfaces as an empty list rather than vanishing from the map.
        if clist or (nm == name and had_conds):
            conditions_out[nm] = clist
    return 200, {
        "id": session["id"],
        "round": session["round"],
        "turn_index": new_index,
        "active": active,
        "conditions": conditions_out,
    }


# ---------------------------------------------------------------------------
# HTTP layer
# ---------------------------------------------------------------------------

POST_ROUTES = {
    "/v1/dice/stats": dice_stats,
    "/v1/checks/ability": ability_check,
    "/v1/encounters/adjusted-xp": adjusted_xp,
    "/v1/initiative/order": initiative_order,
    "/v1/characters/ability-modifier": ability_modifier,
    "/v1/characters/proficiency": proficiency,
    "/v1/characters/derived-stats": derived_stats,
}

COMBAT_SESSIONS_RE = re.compile(r"^/v1/combat/sessions$")
COMBAT_CONDITIONS_RE = re.compile(r"^/v1/combat/sessions/([^/]+)/conditions$")
COMBAT_ADVANCE_RE = re.compile(r"^/v1/combat/sessions/([^/]+)/advance$")


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass  # keep stdout clean

    # -- helpers ----------------------------------------------------------

    def _send_json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _read_json(self):
        try:
            length = int(self.headers.get("Content-Length", 0) or 0)
        except (TypeError, ValueError):
            return None
        raw = self.rfile.read(length) if length > 0 else b""
        if not raw:
            return None
        try:
            return json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None

    def _respond(self, status, payload):
        if payload is None:
            if status == 404:
                self._send_json(404, {"error": "not found"})
            else:
                self._send_json(status, {"error": "invalid request"})
        else:
            self._send_json(status, payload)

    # -- verbs ------------------------------------------------------------

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/health":
            self._send_json(200, {"ok": True})
        else:
            self._send_json(404, {"error": "not found"})

    def do_HEAD(self):
        path = urlparse(self.path).path
        if path == "/health":
            self._send_json(200, {"ok": True})
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self):
        path = urlparse(self.path).path
        handler = POST_ROUTES.get(path)
        if handler is not None:
            body = self._read_json()
            if not isinstance(body, dict):
                self._send_json(400, {"error": "invalid request"})
                return
            result = handler(body)
            if result is None:
                self._send_json(400, {"error": "invalid request"})
                return
            self._send_json(200, result)
            return

        # Combat (stateful) routes
        if COMBAT_SESSIONS_RE.match(path):
            body = self._read_json()
            with SESSIONS_LOCK:
                status, payload = create_session(
                    body if isinstance(body, dict) else None
                )
            self._respond(status, payload)
            return

        m = COMBAT_CONDITIONS_RE.match(path)
        if m:
            sid = unquote(m.group(1))
            body = self._read_json()
            with SESSIONS_LOCK:
                session = SESSIONS.get(sid)
                if session is None:
                    status, payload = 404, None
                else:
                    status, payload = add_condition(
                        session, body if isinstance(body, dict) else None
                    )
            self._respond(status, payload)
            return

        m = COMBAT_ADVANCE_RE.match(path)
        if m:
            sid = unquote(m.group(1))
            self._read_json()  # drain any request body
            with SESSIONS_LOCK:
                session = SESSIONS.get(sid)
                if session is None:
                    status, payload = 404, None
                else:
                    status, payload = advance_turn(session)
            self._respond(status, payload)
            return

        self._send_json(404, {"error": "not found"})


def main():
    port = int(os.environ.get("PORT", "8000"))
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
