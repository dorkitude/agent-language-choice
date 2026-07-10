#!/usr/bin/env python3
import json
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

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

PROFICIENCY_BY_LEVEL = {}
for _lvl in range(1, 21):
    if _lvl <= 4:
        PROFICIENCY_BY_LEVEL[_lvl] = 2
    elif _lvl <= 8:
        PROFICIENCY_BY_LEVEL[_lvl] = 3
    elif _lvl <= 12:
        PROFICIENCY_BY_LEVEL[_lvl] = 4
    elif _lvl <= 16:
        PROFICIENCY_BY_LEVEL[_lvl] = 5
    else:
        PROFICIENCY_BY_LEVEL[_lvl] = 6

ABILITY_KEYS = ("str", "dex", "con", "int", "wis", "cha")

COMBAT_SESSIONS = {}

COMBAT_SESSION_RE = re.compile(r"^/v1/combat/sessions/([^/]+)$")
COMBAT_CONDITIONS_RE = re.compile(r"^/v1/combat/sessions/([^/]+)/conditions$")
COMBAT_ADVANCE_RE = re.compile(r"^/v1/combat/sessions/([^/]+)/advance$")


def ability_modifier(score):
    return (score - 10) // 2


def multiplier_for_count(count):
    if count == 1:
        return 1
    if count == 2:
        return 1.5
    if 3 <= count <= 6:
        return 2
    if 7 <= count <= 10:
        return 2.5
    if 11 <= count <= 14:
        return 3
    return 4


class NotFoundError(Exception):
    pass


class Handler(BaseHTTPRequestHandler):
    def _send_json(self, status, body):
        payload = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _read_json(self):
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw)

    def log_message(self, format, *args):
        pass

    def do_GET(self):
        if self.path == "/health":
            self._send_json(200, {"ok": True})
            return
        self._send_json(404, {"error": "not found"})

    def do_POST(self):
        try:
            if self.path == "/v1/dice/stats":
                self._handle_dice_stats()
            elif self.path == "/v1/checks/ability":
                self._handle_ability_check()
            elif self.path == "/v1/encounters/adjusted-xp":
                self._handle_adjusted_xp()
            elif self.path == "/v1/initiative/order":
                self._handle_initiative_order()
            elif self.path == "/v1/characters/ability-modifier":
                self._handle_ability_modifier()
            elif self.path == "/v1/characters/proficiency":
                self._handle_proficiency()
            elif self.path == "/v1/characters/derived-stats":
                self._handle_derived_stats()
            elif self.path == "/v1/combat/sessions":
                self._handle_create_combat_session()
            elif COMBAT_CONDITIONS_RE.match(self.path):
                session_id = COMBAT_CONDITIONS_RE.match(self.path).group(1)
                self._handle_add_condition(session_id)
            elif COMBAT_ADVANCE_RE.match(self.path):
                session_id = COMBAT_ADVANCE_RE.match(self.path).group(1)
                self._handle_advance_turn(session_id)
            else:
                self._send_json(404, {"error": "not found"})
        except NotFoundError as e:
            self._send_json(404, {"error": str(e)})
        except ValueError as e:
            self._send_json(400, {"error": str(e)})
        except json.JSONDecodeError:
            self._send_json(400, {"error": "invalid json"})

    def _handle_dice_stats(self):
        body = self._read_json()
        expression = body.get("expression", "")
        match = DICE_RE.match(expression.strip()) if isinstance(expression, str) else None
        if not match:
            raise ValueError("invalid expression")
        count = int(match.group(1))
        sides = int(match.group(2))
        modifier = int(match.group(3)) if match.group(3) else 0
        if count <= 0 or sides <= 0:
            raise ValueError("invalid expression")
        min_val = count * 1 + modifier
        max_val = count * sides + modifier
        average = (min_val + max_val) / 2
        if average == int(average):
            average = int(average)
        self._send_json(200, {
            "dice_count": count,
            "sides": sides,
            "modifier": modifier,
            "min": min_val,
            "max": max_val,
            "average": average,
        })

    def _handle_ability_check(self):
        body = self._read_json()
        roll = body.get("roll")
        modifier = body.get("modifier")
        dc = body.get("dc")
        if not all(isinstance(x, (int, float)) for x in (roll, modifier, dc)):
            raise ValueError("invalid request")
        total = roll + modifier
        success = total >= dc
        margin = total - dc
        self._send_json(200, {"total": total, "success": success, "margin": margin})

    def _handle_adjusted_xp(self):
        body = self._read_json()
        party = body.get("party", [])
        monsters = body.get("monsters", [])

        base_xp = 0
        monster_count = 0
        for m in monsters:
            cr = str(m.get("cr"))
            count = m.get("count")
            if cr not in CR_XP or not isinstance(count, int) or count <= 0:
                raise ValueError("invalid monster")
            base_xp += CR_XP[cr] * count
            monster_count += count

        multiplier = multiplier_for_count(monster_count)
        adjusted_xp = base_xp * multiplier
        if adjusted_xp == int(adjusted_xp):
            adjusted_xp = int(adjusted_xp)

        thresholds = {"easy": 0, "medium": 0, "hard": 0, "deadly": 0}
        for member in party:
            level = member.get("level")
            if level not in LEVEL_THRESHOLDS:
                raise ValueError("unsupported level")
            for key in thresholds:
                thresholds[key] += LEVEL_THRESHOLDS[level][key]

        difficulty = "trivial"
        for key in ("easy", "medium", "hard", "deadly"):
            if adjusted_xp >= thresholds[key]:
                difficulty = key

        self._send_json(200, {
            "base_xp": base_xp,
            "monster_count": monster_count,
            "multiplier": multiplier,
            "adjusted_xp": adjusted_xp,
            "difficulty": difficulty,
            "thresholds": thresholds,
        })

    def _handle_initiative_order(self):
        body = self._read_json()
        combatants = body.get("combatants", [])
        scored = []
        for c in combatants:
            name = c.get("name")
            dex = c.get("dex")
            roll = c.get("roll")
            score = roll + dex
            scored.append({"name": name, "dex": dex, "score": score})

        scored.sort(key=lambda c: (-c["score"], -c["dex"], c["name"]))
        order = [{"name": c["name"], "score": c["score"]} for c in scored]
        self._send_json(200, {"order": order})


    def _handle_ability_modifier(self):
        body = self._read_json()
        score = body.get("score")
        if not isinstance(score, int) or isinstance(score, bool) or not (1 <= score <= 30):
            raise ValueError("invalid score")
        self._send_json(200, {"score": score, "modifier": ability_modifier(score)})

    def _handle_proficiency(self):
        body = self._read_json()
        level = body.get("level")
        if not isinstance(level, int) or isinstance(level, bool) or level not in PROFICIENCY_BY_LEVEL:
            raise ValueError("invalid level")
        self._send_json(200, {"level": level, "proficiency_bonus": PROFICIENCY_BY_LEVEL[level]})

    def _handle_derived_stats(self):
        body = self._read_json()
        level = body.get("level")
        abilities = body.get("abilities")
        armor = body.get("armor")

        if not isinstance(level, int) or isinstance(level, bool) or level not in PROFICIENCY_BY_LEVEL:
            raise ValueError("invalid level")
        if not isinstance(abilities, dict):
            raise ValueError("invalid abilities")
        if not isinstance(armor, dict):
            raise ValueError("invalid armor")

        modifiers = {}
        for key in ABILITY_KEYS:
            score = abilities.get(key)
            if not isinstance(score, int) or isinstance(score, bool) or not (1 <= score <= 30):
                raise ValueError("invalid ability score")
            modifiers[key] = ability_modifier(score)

        base = armor.get("base")
        shield = armor.get("shield")
        dex_cap = armor.get("dex_cap")
        if not isinstance(base, int) or isinstance(base, bool):
            raise ValueError("invalid armor base")
        if not isinstance(shield, bool):
            raise ValueError("invalid armor shield")
        if not isinstance(dex_cap, int) or isinstance(dex_cap, bool):
            raise ValueError("invalid armor dex_cap")

        proficiency_bonus = PROFICIENCY_BY_LEVEL[level]
        hp_max = level * (6 + modifiers["con"])
        shield_bonus = 2 if shield else 0
        armor_class = base + min(modifiers["dex"], dex_cap) + shield_bonus

        self._send_json(200, {
            "level": level,
            "proficiency_bonus": proficiency_bonus,
            "hp_max": hp_max,
            "armor_class": armor_class,
            "modifiers": modifiers,
        })


    def _handle_create_combat_session(self):
        body = self._read_json()
        session_id = body.get("id")
        combatants = body.get("combatants")
        if not isinstance(session_id, str) or not session_id:
            raise ValueError("invalid id")
        if session_id in COMBAT_SESSIONS:
            raise ValueError("session already exists")
        if not isinstance(combatants, list) or not combatants:
            raise ValueError("invalid combatants")

        scored = []
        names = set()
        for c in combatants:
            if not isinstance(c, dict):
                raise ValueError("invalid combatant")
            name = c.get("name")
            dex = c.get("dex")
            roll = c.get("roll")
            if not isinstance(name, str) or not name:
                raise ValueError("invalid combatant name")
            if not isinstance(dex, int) or isinstance(dex, bool):
                raise ValueError("invalid combatant dex")
            if not isinstance(roll, int) or isinstance(roll, bool):
                raise ValueError("invalid combatant roll")
            if name in names:
                raise ValueError("duplicate combatant name")
            names.add(name)
            scored.append({"name": name, "dex": dex, "score": roll + dex})

        scored.sort(key=lambda c: (-c["score"], -c["dex"], c["name"]))
        order = [{"name": c["name"], "score": c["score"]} for c in scored]

        session = {
            "id": session_id,
            "round": 1,
            "turn_index": 0,
            "order": order,
            "conditions": {},
        }
        COMBAT_SESSIONS[session_id] = session
        self._send_json(200, self._combat_session_view(session))

    def _combat_session_view(self, session):
        return {
            "id": session["id"],
            "round": session["round"],
            "turn_index": session["turn_index"],
            "active": session["order"][session["turn_index"]],
            "order": session["order"],
        }

    def _get_session(self, session_id):
        session = COMBAT_SESSIONS.get(session_id)
        if session is None:
            raise NotFoundError("session not found")
        return session

    def _handle_add_condition(self, session_id):
        session = self._get_session(session_id)
        body = self._read_json()
        target = body.get("target")
        condition = body.get("condition")
        duration_rounds = body.get("duration_rounds")

        names = {c["name"] for c in session["order"]}
        if not isinstance(target, str) or target not in names:
            raise ValueError("invalid target")
        if not isinstance(condition, str) or not condition:
            raise ValueError("invalid condition")
        if not isinstance(duration_rounds, int) or isinstance(duration_rounds, bool) or duration_rounds <= 0:
            raise ValueError("invalid duration_rounds")

        target_conditions = session["conditions"].setdefault(target, [])
        target_conditions.append({"condition": condition, "remaining_rounds": duration_rounds})

        self._send_json(200, {
            "target": target,
            "conditions": target_conditions,
        })

    def _handle_advance_turn(self, session_id):
        session = self._get_session(session_id)
        order = session["order"]
        next_index = session["turn_index"] + 1
        if next_index >= len(order):
            next_index = 0
            session["round"] += 1
        session["turn_index"] = next_index

        active_name = order[next_index]["name"]
        remaining = []
        for cond in session["conditions"].get(active_name, []):
            cond["remaining_rounds"] -= 1
            if cond["remaining_rounds"] > 0:
                remaining.append(cond)
        if active_name in session["conditions"]:
            session["conditions"][active_name] = remaining

        self._send_json(200, {
            "id": session["id"],
            "round": session["round"],
            "turn_index": session["turn_index"],
            "active": order[next_index],
            "conditions": session["conditions"],
        })


def main():
    port = int(os.environ.get("PORT", "8000"))
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()
