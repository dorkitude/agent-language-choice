import json
import os
import re
from http.server import BaseHTTPRequestHandler, HTTPServer

XP = {
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

sessions = {}


def get_multiplier(monster_count: int):
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


def parse_dice(expression: str):
    match = DICE_RE.match(expression)
    if not match:
        return None
    count = int(match.group(1))
    sides = int(match.group(2))
    modifier = int(match.group(3)) if match.group(3) else 0
    if count <= 0 or sides <= 0:
        return None
    minimum = count + modifier
    maximum = count * sides + modifier
    total = minimum + maximum
    average = total // 2 if total % 2 == 0 else total / 2
    return {
        "dice_count": count,
        "sides": sides,
        "modifier": modifier,
        "min": minimum,
        "max": maximum,
        "average": average,
    }


def ability_modifier(score):
    if type(score) is not int:
        return None
    if not 1 <= score <= 30:
        return None
    return (score - 10) // 2


def proficiency_bonus(level):
    if type(level) is not int:
        return None
    if not 1 <= level <= 20:
        return None
    if level <= 4:
        return 2
    if level <= 8:
        return 3
    if level <= 12:
        return 4
    if level <= 16:
        return 5
    return 6


def derived_stats(data: dict):
    level = data.get("level")
    prof = proficiency_bonus(level)
    if prof is None:
        return None

    abilities = data.get("abilities")
    if not isinstance(abilities, dict):
        return None

    expected = ("str", "dex", "con", "int", "wis", "cha")
    modifiers = {}
    for key in expected:
        score = abilities.get(key)
        mod = ability_modifier(score)
        if mod is None:
            return None
        modifiers[key] = mod

    armor = data.get("armor")
    if not isinstance(armor, dict):
        return None

    base = armor.get("base")
    dex_cap = armor.get("dex_cap")
    if type(base) is not int or type(dex_cap) is not int:
        return None

    shield = armor.get("shield")
    shield_bonus = 2 if shield is True else 0
    armor_class = base + min(modifiers["dex"], dex_cap) + shield_bonus
    hp_max = level * (6 + modifiers["con"])

    return {
        "level": level,
        "proficiency_bonus": prof,
        "hp_max": hp_max,
        "armor_class": armor_class,
        "modifiers": modifiers,
    }


def create_session(data: dict):
    sid = data.get("id")
    if not isinstance(sid, str) or sid in sessions:
        return None
    combatants = data.get("combatants")
    if not isinstance(combatants, list) or not combatants:
        return None
    parsed = []
    for c in combatants:
        if not isinstance(c, dict):
            return None
        name = c.get("name")
        dex = c.get("dex")
        roll = c.get("roll")
        if not isinstance(name, str) or not isinstance(dex, int) or not isinstance(roll, int):
            return None
        parsed.append({"name": name, "dex": dex, "score": roll + dex})
    parsed.sort(key=lambda item: (-item["score"], -item["dex"], item["name"]))
    sessions[sid] = {
        "id": sid,
        "round": 1,
        "turn_index": 0,
        "order": parsed,
        "conditions": {c["name"]: [] for c in parsed},
    }
    return {
        "id": sid,
        "round": 1,
        "turn_index": 0,
        "active": {"name": parsed[0]["name"], "score": parsed[0]["score"]},
        "order": [{"name": c["name"], "score": c["score"]} for c in parsed],
    }


def add_condition(sid: str, data: dict):
    session = sessions.get(sid)
    if not session:
        return None, 404
    target = data.get("target")
    condition = data.get("condition")
    duration = data.get("duration_rounds")
    if (
        not isinstance(target, str)
        or target not in session["conditions"]
        or not isinstance(condition, str)
        or not isinstance(duration, int)
        or duration <= 0
    ):
        return None, 400
    session["conditions"][target].append({"condition": condition, "remaining_rounds": duration})
    return {"target": target, "conditions": list(session["conditions"][target])}, 200


def advance_turn(sid: str):
    session = sessions.get(sid)
    if not session:
        return None, 404
    order = session["order"]
    idx = session["turn_index"] + 1
    if idx >= len(order):
        idx = 0
        session["round"] += 1
    session["turn_index"] = idx
    active = order[idx]
    active_conditions = session["conditions"][active["name"]]
    remaining = []
    for cond in active_conditions:
        cond["remaining_rounds"] -= 1
        if cond["remaining_rounds"] > 0:
            remaining.append(cond)
    session["conditions"][active["name"]] = remaining
    conditions = {name: list(conds) for name, conds in session["conditions"].items()}
    return {
        "id": sid,
        "round": session["round"],
        "turn_index": idx,
        "active": {"name": active["name"], "score": active["score"]},
        "conditions": conditions,
    }, 200


def adjusted_xp(data: dict):
    party = data.get("party", [])
    monsters = data.get("monsters", [])

    base_xp = 0
    monster_count = 0
    for monster in monsters:
        cr = monster.get("cr")
        count = monster.get("count", 0)
        if cr not in XP:
            return None
        base_xp += XP[cr] * count
        monster_count += count

    multiplier = get_multiplier(monster_count)
    adjusted = base_xp * multiplier
    if adjusted == int(adjusted):
        adjusted = int(adjusted)

    thresholds = {"easy": 0, "medium": 0, "hard": 0, "deadly": 0}
    for member in party:
        level = member.get("level")
        level_thresholds = LEVEL_THRESHOLDS.get(level)
        if not level_thresholds:
            continue
        for key in thresholds:
            thresholds[key] += level_thresholds[key]

    if adjusted < thresholds["easy"]:
        difficulty = "trivial"
    elif adjusted < thresholds["medium"]:
        difficulty = "easy"
    elif adjusted < thresholds["hard"]:
        difficulty = "medium"
    elif adjusted < thresholds["deadly"]:
        difficulty = "hard"
    else:
        difficulty = "deadly"

    return {
        "base_xp": base_xp,
        "monster_count": monster_count,
        "multiplier": multiplier,
        "adjusted_xp": adjusted,
        "difficulty": difficulty,
        "thresholds": thresholds,
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        return

    def _send_json(self, status: int, body: dict):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(body).encode("utf-8"))

    def do_GET(self):
        if self.path == "/health":
            self._send_json(200, {"ok": True})
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length > 0 else b""
        try:
            data = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            self._send_json(400, {"error": "invalid json"})
            return

        path = self.path

        if path == "/v1/dice/stats":
            expression = data.get("expression", "")
            if not isinstance(expression, str):
                self._send_json(400, {"error": "invalid expression"})
                return
            result = parse_dice(expression)
            if result is None:
                self._send_json(400, {"error": "invalid expression"})
                return
            self._send_json(200, result)

        elif path == "/v1/checks/ability":
            try:
                roll = int(data["roll"])
                modifier = int(data["modifier"])
                dc = int(data["dc"])
            except (KeyError, TypeError, ValueError):
                self._send_json(400, {"error": "invalid input"})
                return
            total = roll + modifier
            self._send_json(
                200,
                {
                    "total": total,
                    "success": total >= dc,
                    "margin": total - dc,
                },
            )

        elif path == "/v1/encounters/adjusted-xp":
            result = adjusted_xp(data)
            if result is None:
                self._send_json(400, {"error": "invalid input"})
                return
            self._send_json(200, result)

        elif path == "/v1/initiative/order":
            combatants = data.get("combatants", [])
            if not isinstance(combatants, list):
                self._send_json(400, {"error": "invalid input"})
                return
            try:
                scored = []
                for combatant in combatants:
                    name = combatant["name"]
                    dex = int(combatant["dex"])
                    roll = int(combatant["roll"])
                    scored.append((name, dex, roll + dex))
                scored.sort(key=lambda item: (-item[2], -item[1], item[0]))
                order = [{"name": name, "score": score} for name, _, score in scored]
            except (KeyError, TypeError, ValueError):
                self._send_json(400, {"error": "invalid input"})
                return
            self._send_json(200, {"order": order})

        elif path == "/v1/characters/ability-modifier":
            score = data.get("score")
            modifier = ability_modifier(score)
            if modifier is None:
                self._send_json(400, {"error": "invalid input"})
                return
            self._send_json(200, {"score": score, "modifier": modifier})

        elif path == "/v1/characters/proficiency":
            level = data.get("level")
            bonus = proficiency_bonus(level)
            if bonus is None:
                self._send_json(400, {"error": "invalid input"})
                return
            self._send_json(200, {"level": level, "proficiency_bonus": bonus})

        elif path == "/v1/characters/derived-stats":
            result = derived_stats(data)
            if result is None:
                self._send_json(400, {"error": "invalid input"})
                return
            self._send_json(200, result)

        elif path == "/v1/combat/sessions":
            result = create_session(data)
            if result is None:
                self._send_json(400, {"error": "invalid input"})
                return
            self._send_json(200, result)

        elif path.startswith("/v1/combat/sessions/"):
            rest = path[len("/v1/combat/sessions/"):]
            parts = rest.split("/")
            if len(parts) != 2:
                self._send_json(404, {"error": "not found"})
                return
            sid, action = parts
            if action == "conditions":
                result, status = add_condition(sid, data)
            elif action == "advance":
                result, status = advance_turn(sid)
            else:
                self._send_json(404, {"error": "not found"})
                return
            if result is None:
                self._send_json(status, {"error": "not found" if status == 404 else "invalid input"})
                return
            self._send_json(status, result)

        else:
            self._send_json(404, {"error": "not found"})


if __name__ == "__main__":
    host = "127.0.0.1"
    port = int(os.environ.get("PORT", 8000))
    HTTPServer.allow_reuse_address = True
    server = HTTPServer((host, port), Handler)
    server.serve_forever()
