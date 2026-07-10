import math
import os
import re

from flask import Flask, jsonify, request

app = Flask(__name__)

ABILITY_KEYS = ("str", "dex", "con", "int", "wis", "cha")


def ability_modifier(score):
    return math.floor((score - 10) / 2)


def proficiency_bonus(level):
    return 2 + (level - 1) // 4

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

LEVEL_THRESHOLDS = {
    3: {"easy": 75, "medium": 150, "hard": 225, "deadly": 400},
}


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


@app.get("/health")
def health():
    return jsonify(ok=True)


@app.post("/v1/dice/stats")
def dice_stats():
    data = request.get_json(silent=True) or {}
    expression = data.get("expression")
    if not isinstance(expression, str):
        return jsonify(error="invalid expression"), 400

    match = DICE_RE.match(expression.strip())
    if not match:
        return jsonify(error="invalid expression"), 400

    count = int(match.group(1))
    sides = int(match.group(2))
    modifier = int(match.group(3)) if match.group(3) else 0

    if count <= 0 or sides <= 0:
        return jsonify(error="invalid expression"), 400

    minimum = count * 1 + modifier
    maximum = count * sides + modifier
    average = (minimum + maximum) / 2
    if average == int(average):
        average = int(average)

    return jsonify(
        dice_count=count,
        sides=sides,
        modifier=modifier,
        min=minimum,
        max=maximum,
        average=average,
    )


@app.post("/v1/checks/ability")
def ability_check():
    data = request.get_json(silent=True) or {}
    try:
        roll = data["roll"]
        modifier = data["modifier"]
        dc = data["dc"]
    except KeyError:
        return jsonify(error="missing fields"), 400

    total = roll + modifier
    success = total >= dc
    margin = total - dc

    return jsonify(total=total, success=success, margin=margin)


@app.post("/v1/encounters/adjusted-xp")
def adjusted_xp():
    data = request.get_json(silent=True) or {}
    party = data.get("party", [])
    monsters = data.get("monsters", [])

    base_xp = 0
    monster_count = 0
    for monster in monsters:
        cr = str(monster.get("cr"))
        count = monster.get("count", 0)
        xp = CR_XP.get(cr)
        if xp is None:
            return jsonify(error=f"unsupported cr: {cr}"), 400
        base_xp += xp * count
        monster_count += count

    multiplier = multiplier_for_count(monster_count)
    adj_xp = base_xp * multiplier

    thresholds = {"easy": 0, "medium": 0, "hard": 0, "deadly": 0}
    for member in party:
        level = member.get("level")
        level_thresholds = LEVEL_THRESHOLDS.get(level)
        if level_thresholds is None:
            return jsonify(error=f"unsupported level: {level}"), 400
        for key in thresholds:
            thresholds[key] += level_thresholds[key]

    difficulty = "trivial"
    for key in ("easy", "medium", "hard", "deadly"):
        if adj_xp >= thresholds[key]:
            difficulty = key

    return jsonify(
        base_xp=base_xp,
        monster_count=monster_count,
        multiplier=multiplier,
        adjusted_xp=adj_xp,
        difficulty=difficulty,
        thresholds=thresholds,
    )


@app.post("/v1/initiative/order")
def initiative_order():
    data = request.get_json(silent=True) or {}
    combatants = data.get("combatants", [])

    scored = []
    for combatant in combatants:
        name = combatant["name"]
        dex = combatant["dex"]
        roll = combatant["roll"]
        score = roll + dex
        scored.append({"name": name, "dex": dex, "score": score})

    scored.sort(key=lambda c: (-c["score"], -c["dex"], c["name"]))

    order = [{"name": c["name"], "score": c["score"]} for c in scored]

    return jsonify(order=order)


@app.post("/v1/characters/ability-modifier")
def ability_modifier_route():
    data = request.get_json(silent=True) or {}
    score = data.get("score")
    if not isinstance(score, int) or isinstance(score, bool) or not (1 <= score <= 30):
        return jsonify(error="invalid score"), 400

    return jsonify(score=score, modifier=ability_modifier(score))


@app.post("/v1/characters/proficiency")
def proficiency_route():
    data = request.get_json(silent=True) or {}
    level = data.get("level")
    if not isinstance(level, int) or isinstance(level, bool) or not (1 <= level <= 20):
        return jsonify(error="invalid level"), 400

    return jsonify(level=level, proficiency_bonus=proficiency_bonus(level))


COMBAT_SESSIONS = {}


def combatant_public(c):
    return {"name": c["name"], "score": c["score"]}


@app.post("/v1/combat/sessions")
def create_combat_session():
    data = request.get_json(silent=True) or {}
    session_id = data.get("id")
    combatants = data.get("combatants")

    if not isinstance(session_id, str) or not session_id:
        return jsonify(error="invalid id"), 400
    if session_id in COMBAT_SESSIONS:
        return jsonify(error="session already exists"), 400
    if not isinstance(combatants, list) or not combatants:
        return jsonify(error="invalid combatants"), 400

    scored = []
    for combatant in combatants:
        if not isinstance(combatant, dict):
            return jsonify(error="invalid combatant"), 400
        name = combatant.get("name")
        dex = combatant.get("dex")
        roll = combatant.get("roll")
        if not isinstance(name, str) or not name:
            return jsonify(error="invalid combatant name"), 400
        if not isinstance(dex, int) or isinstance(dex, bool):
            return jsonify(error="invalid combatant dex"), 400
        if not isinstance(roll, int) or isinstance(roll, bool):
            return jsonify(error="invalid combatant roll"), 400
        scored.append({
            "name": name,
            "dex": dex,
            "score": roll + dex,
            "conditions": [],
        })

    scored.sort(key=lambda c: (-c["score"], -c["dex"], c["name"]))

    session = {
        "id": session_id,
        "round": 1,
        "turn_index": 0,
        "order": scored,
    }
    COMBAT_SESSIONS[session_id] = session

    return jsonify(
        id=session_id,
        round=session["round"],
        turn_index=session["turn_index"],
        active=combatant_public(scored[session["turn_index"]]),
        order=[combatant_public(c) for c in scored],
    )


@app.post("/v1/combat/sessions/<session_id>/conditions")
def add_combat_condition(session_id):
    session = COMBAT_SESSIONS.get(session_id)
    if session is None:
        return jsonify(error="session not found"), 404

    data = request.get_json(silent=True) or {}
    target = data.get("target")
    condition = data.get("condition")
    duration_rounds = data.get("duration_rounds")

    if not isinstance(target, str) or not target:
        return jsonify(error="invalid target"), 400
    if not isinstance(condition, str) or not condition:
        return jsonify(error="invalid condition"), 400
    if not isinstance(duration_rounds, int) or isinstance(duration_rounds, bool) or duration_rounds <= 0:
        return jsonify(error="invalid duration_rounds"), 400

    combatant = next((c for c in session["order"] if c["name"] == target), None)
    if combatant is None:
        return jsonify(error="unknown target"), 400

    combatant["conditions"].append({
        "condition": condition,
        "remaining_rounds": duration_rounds,
    })

    return jsonify(
        target=target,
        conditions=[dict(c) for c in combatant["conditions"]],
    )


@app.post("/v1/combat/sessions/<session_id>/advance")
def advance_combat_turn(session_id):
    session = COMBAT_SESSIONS.get(session_id)
    if session is None:
        return jsonify(error="session not found"), 404

    order = session["order"]
    next_index = session["turn_index"] + 1
    if next_index >= len(order):
        next_index = 0
        session["round"] += 1
    session["turn_index"] = next_index

    active = order[next_index]
    remaining = []
    for condition in active["conditions"]:
        condition["remaining_rounds"] -= 1
        if condition["remaining_rounds"] > 0:
            remaining.append(condition)
    active["conditions"] = remaining

    conditions_by_name = {
        c["name"]: [dict(cond) for cond in c["conditions"]]
        for c in order
        if c["conditions"] or c is active
    }

    return jsonify(
        id=session_id,
        round=session["round"],
        turn_index=session["turn_index"],
        active=combatant_public(active),
        conditions=conditions_by_name,
    )


@app.post("/v1/characters/derived-stats")
def derived_stats():
    data = request.get_json(silent=True) or {}
    level = data.get("level")
    abilities = data.get("abilities")
    armor = data.get("armor")

    if not isinstance(level, int) or isinstance(level, bool) or not (1 <= level <= 20):
        return jsonify(error="invalid level"), 400
    if not isinstance(abilities, dict) or any(k not in abilities for k in ABILITY_KEYS):
        return jsonify(error="invalid abilities"), 400
    for key in ABILITY_KEYS:
        value = abilities[key]
        if not isinstance(value, int) or isinstance(value, bool) or not (1 <= value <= 30):
            return jsonify(error=f"invalid ability score: {key}"), 400
    if not isinstance(armor, dict):
        return jsonify(error="invalid armor"), 400

    base = armor.get("base")
    shield = armor.get("shield", False)
    dex_cap = armor.get("dex_cap")
    if not isinstance(base, int) or isinstance(base, bool):
        return jsonify(error="invalid armor base"), 400
    if not isinstance(dex_cap, int) or isinstance(dex_cap, bool):
        return jsonify(error="invalid armor dex_cap"), 400
    if not isinstance(shield, bool):
        return jsonify(error="invalid armor shield"), 400

    modifiers = {key: ability_modifier(abilities[key]) for key in ABILITY_KEYS}
    prof_bonus = proficiency_bonus(level)
    hp_max = level * (6 + modifiers["con"])
    shield_bonus = 2 if shield else 0
    armor_class = base + min(modifiers["dex"], dex_cap) + shield_bonus

    return jsonify(
        level=level,
        proficiency_bonus=prof_bonus,
        hp_max=hp_max,
        armor_class=armor_class,
        modifiers=modifiers,
    )


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ["PORT"]))
