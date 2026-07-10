import os
import re

from flask import Flask, jsonify, request

app = Flask(__name__)


DICE_RE = re.compile(r"^([0-9]+)d([0-9]+)(?:([+-])([0-9]+))?$")

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

ABILITY_KEYS = ("str", "dex", "con", "int", "wis", "cha")

COMBAT_SESSIONS = {}


def bad_request():
    return jsonify(error="bad_request"), 400


def not_found():
    return jsonify(error="not_found"), 404


def json_body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ValueError("JSON object required")
    return data


def required_int(data, key):
    value = data.get(key)
    if type(value) is not int:
        raise ValueError(f"{key} must be an integer")
    return value


def clean_number(value):
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def ability_modifier(score):
    if type(score) is not int or score < 1 or score > 30:
        raise ValueError("score must be an integer from 1 through 30")
    return (score - 10) // 2


def proficiency_bonus(level):
    if type(level) is not int or level < 1 or level > 20:
        raise ValueError("level must be an integer from 1 through 20")
    return 2 + (level - 1) // 4


def initiative_entries(combatants, allow_empty=True):
    if not isinstance(combatants, list) or (len(combatants) == 0 and not allow_empty):
        raise ValueError("combatants must be a list")

    entries = []
    for combatant in combatants:
        if not isinstance(combatant, dict):
            raise ValueError("combatant must be an object")
        name = combatant.get("name")
        if not isinstance(name, str):
            raise ValueError("name must be a string")
        dex = required_int(combatant, "dex")
        roll = required_int(combatant, "roll")
        score = roll + dex
        entries.append({"name": name, "dex": dex, "score": score})

    entries.sort(key=lambda item: (-item["score"], -item["dex"], item["name"]))
    return entries


def combat_public_state(session, include_conditions=False):
    response = {
        "id": session["id"],
        "round": session["round"],
        "turn_index": session["turn_index"],
        "active": session["order"][session["turn_index"]],
        "order": session["order"],
    }
    if include_conditions:
        response["conditions"] = active_conditions(session)
        del response["order"]
    return response


def active_conditions(session):
    return {
        name: conditions
        for name, conditions in session["conditions"].items()
        if len(conditions) > 0 or name in session["condition_targets"]
    }


@app.get("/health")
def health():
    return jsonify(ok=True)


@app.post("/v1/dice/stats")
def dice_stats():
    try:
        data = json_body()
        expression = data.get("expression")
        if not isinstance(expression, str):
            return bad_request()

        match = DICE_RE.fullmatch(expression)
        if match is None:
            return bad_request()

        dice_count = int(match.group(1))
        sides = int(match.group(2))
        if dice_count <= 0 or sides <= 0:
            return bad_request()

        modifier = int(match.group(4) or 0)
        if match.group(3) == "-":
            modifier = -modifier

        minimum = dice_count + modifier
        maximum = dice_count * sides + modifier
        average = dice_count * (sides + 1) / 2 + modifier
        return jsonify(
            dice_count=dice_count,
            sides=sides,
            modifier=modifier,
            min=minimum,
            max=maximum,
            average=clean_number(average),
        )
    except (TypeError, ValueError):
        return bad_request()


@app.post("/v1/checks/ability")
def ability_check():
    try:
        data = json_body()
        roll = required_int(data, "roll")
        modifier = required_int(data, "modifier")
        dc = required_int(data, "dc")
        total = roll + modifier
        return jsonify(total=total, success=total >= dc, margin=total - dc)
    except (TypeError, ValueError):
        return bad_request()


def monster_multiplier(monster_count):
    if monster_count <= 0:
        raise ValueError("monster_count must be positive")
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


@app.post("/v1/encounters/adjusted-xp")
def adjusted_xp():
    try:
        data = json_body()
        party = data.get("party")
        monsters = data.get("monsters")
        if not isinstance(party, list) or not isinstance(monsters, list):
            return bad_request()

        thresholds = {"easy": 0, "medium": 0, "hard": 0, "deadly": 0}
        for member in party:
            if not isinstance(member, dict):
                return bad_request()
            level = required_int(member, "level")
            if level not in LEVEL_THRESHOLDS:
                return bad_request()
            for name, value in LEVEL_THRESHOLDS[level].items():
                thresholds[name] += value

        base_xp = 0
        monster_count = 0
        for monster in monsters:
            if not isinstance(monster, dict):
                return bad_request()
            cr = monster.get("cr")
            count = required_int(monster, "count")
            if cr not in CR_XP or count <= 0:
                return bad_request()
            base_xp += CR_XP[cr] * count
            monster_count += count

        multiplier = monster_multiplier(monster_count)
        adjusted = base_xp * multiplier
        difficulty = "trivial"
        for name in ("easy", "medium", "hard", "deadly"):
            if adjusted >= thresholds[name]:
                difficulty = name

        return jsonify(
            base_xp=base_xp,
            monster_count=monster_count,
            multiplier=clean_number(multiplier),
            adjusted_xp=clean_number(adjusted),
            difficulty=difficulty,
            thresholds=thresholds,
        )
    except (TypeError, ValueError):
        return bad_request()


@app.post("/v1/initiative/order")
def initiative_order():
    try:
        data = json_body()
        combatants = data.get("combatants")
        entries = initiative_entries(combatants)
        return jsonify(order=[{"name": item["name"], "score": item["score"]} for item in entries])
    except (TypeError, ValueError):
        return bad_request()


@app.post("/v1/characters/ability-modifier")
def character_ability_modifier():
    try:
        data = json_body()
        score = required_int(data, "score")
        return jsonify(score=score, modifier=ability_modifier(score))
    except (TypeError, ValueError):
        return bad_request()


@app.post("/v1/characters/proficiency")
def character_proficiency():
    try:
        data = json_body()
        level = required_int(data, "level")
        return jsonify(level=level, proficiency_bonus=proficiency_bonus(level))
    except (TypeError, ValueError):
        return bad_request()


@app.post("/v1/characters/derived-stats")
def character_derived_stats():
    try:
        data = json_body()
        level = required_int(data, "level")
        bonus = proficiency_bonus(level)

        abilities = data.get("abilities")
        armor = data.get("armor")
        if not isinstance(abilities, dict) or not isinstance(armor, dict):
            return bad_request()

        modifiers = {}
        for key in ABILITY_KEYS:
            modifiers[key] = ability_modifier(required_int(abilities, key))

        armor_base = required_int(armor, "base")
        dex_cap = required_int(armor, "dex_cap")
        shield = armor.get("shield")
        if type(shield) is not bool:
            return bad_request()

        hp_max = level * (6 + modifiers["con"])
        armor_class = armor_base + min(modifiers["dex"], dex_cap) + (2 if shield else 0)
        return jsonify(
            level=level,
            proficiency_bonus=bonus,
            hp_max=hp_max,
            armor_class=armor_class,
            modifiers=modifiers,
        )
    except (TypeError, ValueError):
        return bad_request()


@app.post("/v1/combat/sessions")
def create_combat_session():
    try:
        data = json_body()
        session_id = data.get("id")
        if not isinstance(session_id, str) or session_id in COMBAT_SESSIONS:
            return bad_request()

        entries = initiative_entries(data.get("combatants"), allow_empty=False)
        names = [entry["name"] for entry in entries]
        if len(set(names)) != len(names):
            return bad_request()

        session = {
            "id": session_id,
            "round": 1,
            "turn_index": 0,
            "order": [{"name": entry["name"], "score": entry["score"]} for entry in entries],
            "combatants": set(names),
            "conditions": {name: [] for name in names},
            "condition_targets": set(),
        }
        COMBAT_SESSIONS[session_id] = session
        return jsonify(combat_public_state(session))
    except (TypeError, ValueError):
        return bad_request()


@app.post("/v1/combat/sessions/<session_id>/conditions")
def add_combat_condition(session_id):
    session = COMBAT_SESSIONS.get(session_id)
    if session is None:
        return not_found()

    try:
        data = json_body()
        target = data.get("target")
        condition = data.get("condition")
        duration_rounds = data.get("duration_rounds")
        if target not in session["combatants"]:
            return bad_request()
        if not isinstance(condition, str):
            return bad_request()
        if type(duration_rounds) is not int or duration_rounds <= 0:
            return bad_request()

        session["conditions"][target].append(
            {"condition": condition, "remaining_rounds": duration_rounds}
        )
        session["condition_targets"].add(target)
        return jsonify(target=target, conditions=session["conditions"][target])
    except (TypeError, ValueError):
        return bad_request()


@app.post("/v1/combat/sessions/<session_id>/advance")
def advance_combat_turn(session_id):
    session = COMBAT_SESSIONS.get(session_id)
    if session is None:
        return not_found()

    session["turn_index"] += 1
    if session["turn_index"] == len(session["order"]):
        session["turn_index"] = 0
        session["round"] += 1

    active_name = session["order"][session["turn_index"]]["name"]
    remaining_conditions = []
    for condition in session["conditions"][active_name]:
        condition["remaining_rounds"] -= 1
        if condition["remaining_rounds"] > 0:
            remaining_conditions.append(condition)
    session["conditions"][active_name] = remaining_conditions

    return jsonify(combat_public_state(session, include_conditions=True))


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ["PORT"]))
