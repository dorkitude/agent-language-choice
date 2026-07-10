import os
import re

from flask import Flask, jsonify, request

app = Flask(__name__)

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


def count_multiplier(monster_count):
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
    dice_count = int(match.group(1))
    sides = int(match.group(2))
    modifier = int(match.group(3)) if match.group(3) else 0
    if dice_count <= 0 or sides <= 0:
        return jsonify(error="invalid expression"), 400
    minimum = dice_count * 1 + modifier
    maximum = dice_count * sides + modifier
    average = (minimum + maximum) / 2
    return jsonify(
        dice_count=dice_count,
        sides=sides,
        modifier=modifier,
        min=minimum,
        max=maximum,
        average=average,
    )


@app.post("/v1/checks/ability")
def ability_check():
    data = request.get_json(silent=True) or {}
    roll = data.get("roll")
    modifier = data.get("modifier")
    dc = data.get("dc")
    if not all(isinstance(v, int) for v in (roll, modifier, dc)):
        return jsonify(error="invalid request"), 400
    total = roll + modifier
    return jsonify(total=total, success=total >= dc, margin=total - dc)


@app.post("/v1/encounters/adjusted-xp")
def adjusted_xp():
    data = request.get_json(silent=True) or {}
    party = data.get("party")
    monsters = data.get("monsters")
    if not isinstance(party, list) or not isinstance(monsters, list):
        return jsonify(error="invalid request"), 400

    base_xp = 0
    monster_count = 0
    for monster in monsters:
        if not isinstance(monster, dict):
            return jsonify(error="invalid monster"), 400
        cr = monster.get("cr")
        count = monster.get("count", 1)
        if cr not in CR_XP or not isinstance(count, int) or count < 0:
            return jsonify(error="invalid monster"), 400
        base_xp += CR_XP[cr] * count
        monster_count += count

    multiplier = count_multiplier(monster_count)
    adjusted = base_xp * multiplier
    adjusted = int(adjusted) if adjusted == int(adjusted) else adjusted

    thresholds = {"easy": 0, "medium": 0, "hard": 0, "deadly": 0}
    for member in party:
        if not isinstance(member, dict):
            return jsonify(error="invalid party member"), 400
        level = member.get("level")
        if level not in LEVEL_THRESHOLDS:
            return jsonify(error="unsupported level"), 400
        for key, value in LEVEL_THRESHOLDS[level].items():
            thresholds[key] += value

    difficulty = "trivial"
    for key in ("easy", "medium", "hard", "deadly"):
        if adjusted >= thresholds[key]:
            difficulty = key

    return jsonify(
        base_xp=base_xp,
        monster_count=monster_count,
        multiplier=multiplier,
        adjusted_xp=adjusted,
        difficulty=difficulty,
        thresholds=thresholds,
    )


@app.post("/v1/initiative/order")
def initiative_order():
    data = request.get_json(silent=True) or {}
    combatants = data.get("combatants")
    if not isinstance(combatants, list):
        return jsonify(error="invalid request"), 400

    entries = []
    for c in combatants:
        if not isinstance(c, dict):
            return jsonify(error="invalid combatant"), 400
        name = c.get("name")
        dex = c.get("dex")
        roll = c.get("roll")
        if not isinstance(name, str) or not isinstance(dex, int) or not isinstance(roll, int):
            return jsonify(error="invalid combatant"), 400
        entries.append({"name": name, "dex": dex, "score": roll + dex})

    entries.sort(key=lambda e: (-e["score"], -e["dex"], e["name"]))
    order = [{"name": e["name"], "score": e["score"]} for e in entries]
    return jsonify(order=order)


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def ability_modifier(score):
    return (score - 10) // 2


def proficiency_bonus(level):
    return (level + 7) // 4


@app.post("/v1/characters/ability-modifier")
def characters_ability_modifier():
    data = request.get_json(silent=True) or {}
    score = data.get("score")
    if not _is_int(score) or score < 1 or score > 30:
        return jsonify(error="invalid score"), 400
    return jsonify(score=score, modifier=ability_modifier(score))


@app.post("/v1/characters/proficiency")
def characters_proficiency():
    data = request.get_json(silent=True) or {}
    level = data.get("level")
    if not _is_int(level) or level < 1 or level > 20:
        return jsonify(error="invalid level"), 400
    return jsonify(level=level, proficiency_bonus=proficiency_bonus(level))


@app.post("/v1/characters/derived-stats")
def characters_derived_stats():
    data = request.get_json(silent=True) or {}
    level = data.get("level")
    abilities = data.get("abilities")
    armor = data.get("armor")
    if not _is_int(level) or level < 1 or level > 20:
        return jsonify(error="invalid level"), 400
    if not isinstance(abilities, dict) or not isinstance(armor, dict):
        return jsonify(error="invalid request"), 400

    modifiers = {}
    for key in ("str", "dex", "con", "int", "wis", "cha"):
        score = abilities.get(key)
        if not _is_int(score) or score < 1 or score > 30:
            return jsonify(error="invalid abilities"), 400
        modifiers[key] = ability_modifier(score)

    base = armor.get("base")
    dex_cap = armor.get("dex_cap")
    shield = armor.get("shield")
    if not _is_int(base) or not _is_int(dex_cap) or not isinstance(shield, bool):
        return jsonify(error="invalid armor"), 400

    proficiency = proficiency_bonus(level)
    hp_max = level * (6 + modifiers["con"])
    shield_bonus = 2 if shield else 0
    armor_class = base + min(modifiers["dex"], dex_cap) + shield_bonus

    return jsonify(
        level=level,
        proficiency_bonus=proficiency,
        hp_max=hp_max,
        armor_class=armor_class,
        modifiers=modifiers,
    )


COMBAT_SESSIONS = {}


def _combat_order(session):
    return [{"name": c["name"], "score": c["score"]} for c in session["order"]]


def _active(session):
    combatant = session["order"][session["turn_index"]]
    return {"name": combatant["name"], "score": combatant["score"]}


def _conditions_map(session):
    result = {}
    for combatant in session["order"]:
        conds = combatant["conditions"]
        if conds or combatant.get("had_condition"):
            result[combatant["name"]] = [
                {"condition": c["condition"], "remaining_rounds": c["remaining_rounds"]}
                for c in conds
            ]
    return result


@app.post("/v1/combat/sessions")
def combat_create_session():
    data = request.get_json(silent=True) or {}
    session_id = data.get("id")
    combatants = data.get("combatants")
    if not isinstance(session_id, str) or not session_id:
        return jsonify(error="invalid id"), 400
    if session_id in COMBAT_SESSIONS:
        return jsonify(error="duplicate id"), 400
    if not isinstance(combatants, list) or not combatants:
        return jsonify(error="invalid combatants"), 400

    entries = []
    for c in combatants:
        if not isinstance(c, dict):
            return jsonify(error="invalid combatant"), 400
        name = c.get("name")
        dex = c.get("dex")
        roll = c.get("roll")
        if not isinstance(name, str) or not _is_int(dex) or not _is_int(roll):
            return jsonify(error="invalid combatant"), 400
        entries.append(
            {"name": name, "dex": dex, "score": roll + dex, "conditions": []}
        )

    entries.sort(key=lambda e: (-e["score"], -e["dex"], e["name"]))
    session = {"id": session_id, "round": 1, "turn_index": 0, "order": entries}
    COMBAT_SESSIONS[session_id] = session

    return jsonify(
        id=session_id,
        round=session["round"],
        turn_index=session["turn_index"],
        active=_active(session),
        order=_combat_order(session),
    )


@app.post("/v1/combat/sessions/<sid>/conditions")
def combat_add_condition(sid):
    session = COMBAT_SESSIONS.get(sid)
    if session is None:
        return jsonify(error="unknown session"), 404

    data = request.get_json(silent=True) or {}
    target = data.get("target")
    condition = data.get("condition")
    duration = data.get("duration_rounds")
    if not isinstance(target, str) or not isinstance(condition, str):
        return jsonify(error="invalid request"), 400
    if not _is_int(duration) or duration <= 0:
        return jsonify(error="invalid duration_rounds"), 400

    combatant = next((c for c in session["order"] if c["name"] == target), None)
    if combatant is None:
        return jsonify(error="unknown target"), 400

    combatant["had_condition"] = True
    combatant["conditions"].append(
        {"condition": condition, "remaining_rounds": duration}
    )

    return jsonify(
        target=target,
        conditions=[
            {"condition": c["condition"], "remaining_rounds": c["remaining_rounds"]}
            for c in combatant["conditions"]
        ],
    )


@app.post("/v1/combat/sessions/<sid>/advance")
def combat_advance(sid):
    session = COMBAT_SESSIONS.get(sid)
    if session is None:
        return jsonify(error="unknown session"), 404

    count = len(session["order"])
    session["turn_index"] += 1
    if session["turn_index"] >= count:
        session["turn_index"] = 0
        session["round"] += 1

    active = session["order"][session["turn_index"]]
    remaining = []
    for cond in active["conditions"]:
        cond["remaining_rounds"] -= 1
        if cond["remaining_rounds"] > 0:
            remaining.append(cond)
    active["conditions"] = remaining

    return jsonify(
        id=session["id"],
        round=session["round"],
        turn_index=session["turn_index"],
        active=_active(session),
        conditions=_conditions_map(session),
    )


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ["PORT"]))
