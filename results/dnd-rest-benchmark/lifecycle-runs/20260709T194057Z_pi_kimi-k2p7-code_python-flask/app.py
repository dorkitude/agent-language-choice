from flask import Flask, jsonify, request
import os
import re

app = Flask(__name__)

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

ABILITY_NAMES = ("str", "dex", "con", "int", "wis", "cha")


def _ability_modifier(score: int) -> int:
    return (score - 10) // 2


def _proficiency_bonus(level: int) -> int:
    if level <= 4:
        return 2
    if level <= 8:
        return 3
    if level <= 12:
        return 4
    if level <= 16:
        return 5
    return 6


def _dice_multiplier(monster_count: int) -> float:
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
    return 4


@app.get("/health")
def health():
    return jsonify(ok=True)


@app.post("/v1/dice/stats")
def dice_stats():
    data = request.get_json(silent=True) or {}
    expression = data.get("expression", "")

    match = re.fullmatch(r"(\d+)d(\d+)([+-]\d+)?", str(expression))
    if not match:
        return jsonify(error="invalid expression"), 400

    count = int(match.group(1))
    sides = int(match.group(2))
    modifier = int(match.group(3) or "0")

    if count <= 0 or sides <= 0:
        return jsonify(error="invalid expression"), 400

    min_value = count + modifier
    max_value = count * sides + modifier
    average = count * (sides + 1) / 2 + modifier
    if average == int(average):
        average = int(average)

    return jsonify(
        dice_count=count,
        sides=sides,
        modifier=modifier,
        min=min_value,
        max=max_value,
        average=average,
    )


@app.post("/v1/checks/ability")
def ability_check():
    data = request.get_json(silent=True) or {}
    roll = data.get("roll", 0)
    modifier = data.get("modifier", 0)
    dc = data.get("dc", 0)
    total = roll + modifier
    return jsonify(total=total, success=total >= dc, margin=total - dc)


@app.post("/v1/encounters/adjusted-xp")
def adjusted_xp():
    data = request.get_json(silent=True) or {}
    party = data.get("party", [])
    monsters = data.get("monsters", [])

    base_xp = 0
    monster_count = 0
    for monster in monsters:
        cr = monster.get("cr")
        count = monster.get("count", 0)
        xp = CR_XP.get(str(cr))
        if xp is None or count <= 0:
            return jsonify(error="invalid monster"), 400
        base_xp += xp * count
        monster_count += count

    if monster_count <= 0:
        return jsonify(error="invalid encounter"), 400

    multiplier = _dice_multiplier(monster_count)
    adjusted_xp = int(base_xp * multiplier)

    thresholds = {"easy": 0, "medium": 0, "hard": 0, "deadly": 0}
    for member in party:
        level = member.get("level")
        level_thresholds = LEVEL_THRESHOLDS.get(level)
        if level_thresholds is None:
            return jsonify(error="unsupported party level"), 400
        for key in thresholds:
            thresholds[key] += level_thresholds[key]

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

    return jsonify(
        base_xp=base_xp,
        monster_count=monster_count,
        multiplier=multiplier,
        adjusted_xp=adjusted_xp,
        difficulty=difficulty,
        thresholds=thresholds,
    )


@app.post("/v1/initiative/order")
def initiative_order():
    data = request.get_json(silent=True) or {}
    combatants = data.get("combatants", [])

    scored = []
    for combatant in combatants:
        name = combatant.get("name")
        dex = combatant.get("dex", 0)
        roll = combatant.get("roll", 0)
        scored.append({"name": name, "score": roll + dex, "dex": dex})

    scored.sort(key=lambda c: (-c["score"], -c["dex"], c["name"]))
    return jsonify(order=[{"name": c["name"], "score": c["score"]} for c in scored])


@app.post("/v1/characters/ability-modifier")
def ability_modifier():
    data = request.get_json(silent=True) or {}
    score = data.get("score")
    if not isinstance(score, int) or score < 1 or score > 30:
        return jsonify(error="invalid score"), 400
    return jsonify(score=score, modifier=_ability_modifier(score))


@app.post("/v1/characters/proficiency")
def proficiency():
    data = request.get_json(silent=True) or {}
    level = data.get("level")
    if not isinstance(level, int) or level < 1 or level > 20:
        return jsonify(error="invalid level"), 400
    return jsonify(level=level, proficiency_bonus=_proficiency_bonus(level))


@app.post("/v1/characters/derived-stats")
def derived_stats():
    data = request.get_json(silent=True) or {}
    level = data.get("level")
    if not isinstance(level, int) or level < 1 or level > 20:
        return jsonify(error="invalid level"), 400

    abilities = data.get("abilities", {})
    if not isinstance(abilities, dict):
        return jsonify(error="invalid abilities"), 400
    modifiers = {}
    for name in ABILITY_NAMES:
        score = abilities.get(name)
        if not isinstance(score, int) or score < 1 or score > 30:
            return jsonify(error=f"invalid ability {name}"), 400
        modifiers[name] = _ability_modifier(score)

    armor = data.get("armor", {})
    if not isinstance(armor, dict):
        return jsonify(error="invalid armor"), 400
    base = armor.get("base")
    if not isinstance(base, int) or base < 0:
        return jsonify(error="invalid armor base"), 400
    shield = armor.get("shield")
    if not isinstance(shield, bool):
        return jsonify(error="invalid armor shield"), 400
    dex_cap = armor.get("dex_cap")
    if not isinstance(dex_cap, int) or dex_cap < 0:
        return jsonify(error="invalid armor dex_cap"), 400

    shield_bonus = 2 if shield else 0
    armor_class = base + min(modifiers["dex"], dex_cap) + shield_bonus
    hp_max = level * (6 + modifiers["con"])

    return jsonify(
        level=level,
        proficiency_bonus=_proficiency_bonus(level),
        hp_max=hp_max,
        armor_class=armor_class,
        modifiers=modifiers,
    )


combat_sessions: dict[str, dict] = {}


def _combatant_exists(session: dict, target: str) -> bool:
    return any(c["name"] == target for c in session["combatants"])


def _get_active(session: dict) -> dict:
    return session["order"][session["turn_index"]]


def _build_conditions_response(session: dict) -> dict:
    return {
        c["name"]: [{"condition": cond["condition"], "remaining_rounds": cond["remaining_rounds"]} for cond in c["conditions"]]
        for c in session["combatants"]
    }


@app.post("/v1/combat/sessions")
def create_combat_session():
    data = request.get_json(silent=True) or {}

    session_id = data.get("id")
    if not isinstance(session_id, str) or not session_id:
        return jsonify(error="invalid id"), 400
    if session_id in combat_sessions:
        return jsonify(error="session already exists"), 400

    combatants = data.get("combatants", [])
    if not isinstance(combatants, list) or len(combatants) == 0:
        return jsonify(error="invalid combatants"), 400

    parsed = []
    for combatant in combatants:
        name = combatant.get("name")
        dex = combatant.get("dex", 0)
        roll = combatant.get("roll", 0)
        if not isinstance(name, str) or not name:
            return jsonify(error="invalid combatant name"), 400
        if not isinstance(dex, int) or not isinstance(roll, int):
            return jsonify(error="invalid combatant stats"), 400
        parsed.append({"name": name, "dex": dex, "roll": roll, "conditions": []})

    ordered = sorted(parsed, key=lambda c: (-(c["roll"] + c["dex"]), -c["dex"], c["name"]))
    order = [{"name": c["name"], "score": c["roll"] + c["dex"]} for c in ordered]

    session = {
        "id": session_id,
        "combatants": ordered,
        "order": order,
        "round": 1,
        "turn_index": 0,
    }
    combat_sessions[session_id] = session

    return jsonify(
        id=session_id,
        round=1,
        turn_index=0,
        active=order[0],
        order=order,
    )


@app.post("/v1/combat/sessions/<session_id>/conditions")
def add_condition(session_id: str):
    session = combat_sessions.get(session_id)
    if session is None:
        return jsonify(error="session not found"), 404

    data = request.get_json(silent=True) or {}
    target = data.get("target")
    condition = data.get("condition")
    duration_rounds = data.get("duration_rounds")

    if not isinstance(target, str) or not target or not _combatant_exists(session, target):
        return jsonify(error="invalid target"), 400
    if not isinstance(condition, str) or not condition:
        return jsonify(error="invalid condition"), 400
    if not isinstance(duration_rounds, int) or duration_rounds <= 0:
        return jsonify(error="invalid duration_rounds"), 400

    for combatant in session["combatants"]:
        if combatant["name"] == target:
            combatant["conditions"].append({"condition": condition, "remaining_rounds": duration_rounds})
            return jsonify(
                target=target,
                conditions=[{"condition": c["condition"], "remaining_rounds": c["remaining_rounds"]} for c in combatant["conditions"]],
            )

    return jsonify(error="invalid target"), 400


@app.post("/v1/combat/sessions/<session_id>/advance")
def advance_turn(session_id: str):
    session = combat_sessions.get(session_id)
    if session is None:
        return jsonify(error="session not found"), 404

    order_count = len(session["order"])
    if order_count == 0:
        return jsonify(error="empty session"), 400

    session["turn_index"] += 1
    if session["turn_index"] >= order_count:
        session["turn_index"] = 0
        session["round"] += 1

    active_name = _get_active(session)["name"]
    for combatant in session["combatants"]:
        if combatant["name"] == active_name:
            for cond in combatant["conditions"]:
                cond["remaining_rounds"] -= 1
            combatant["conditions"] = [cond for cond in combatant["conditions"] if cond["remaining_rounds"] > 0]
            break

    return jsonify(
        id=session_id,
        round=session["round"],
        turn_index=session["turn_index"],
        active=_get_active(session),
        conditions=_build_conditions_response(session),
    )


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ["PORT"]))
