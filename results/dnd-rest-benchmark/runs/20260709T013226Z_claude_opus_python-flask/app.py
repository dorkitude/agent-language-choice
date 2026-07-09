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

# Encounter thresholds per character level.
LEVEL_THRESHOLDS = {
    3: {"easy": 75, "medium": 150, "hard": 225, "deadly": 400},
}

DICE_RE = re.compile(r"^\s*(\d+)d(\d+)([+-]\d+)?\s*$")


def _bad_request(message):
    return jsonify(error=message), 400


@app.get("/health")
def health():
    return jsonify(ok=True)


@app.post("/v1/dice/stats")
def dice_stats():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return _bad_request("invalid body")
    expression = body.get("expression")
    if not isinstance(expression, str):
        return _bad_request("invalid expression")
    match = DICE_RE.match(expression)
    if not match:
        return _bad_request("invalid expression")
    count = int(match.group(1))
    sides = int(match.group(2))
    modifier = int(match.group(3)) if match.group(3) else 0
    if count <= 0 or sides <= 0:
        return _bad_request("count and sides must be positive")
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
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return _bad_request("invalid body")
    try:
        roll = int(body["roll"])
        modifier = int(body["modifier"])
        dc = int(body["dc"])
    except (KeyError, TypeError, ValueError):
        return _bad_request("invalid body")
    total = roll + modifier
    return jsonify(total=total, success=total >= dc, margin=total - dc)


def _count_multiplier(count):
    if count <= 1:
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


@app.post("/v1/encounters/adjusted-xp")
def adjusted_xp():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return _bad_request("invalid body")
    party = body.get("party")
    monsters = body.get("monsters")
    if not isinstance(party, list) or not isinstance(monsters, list):
        return _bad_request("invalid body")

    base_xp = 0
    monster_count = 0
    try:
        for monster in monsters:
            cr = monster["cr"]
            count = int(monster["count"])
            if cr not in CR_XP:
                return _bad_request("unsupported CR")
            if count < 0:
                return _bad_request("invalid count")
            base_xp += CR_XP[cr] * count
            monster_count += count
    except (KeyError, TypeError, ValueError):
        return _bad_request("invalid monster")

    multiplier = _count_multiplier(monster_count)
    adjusted = base_xp * multiplier
    if adjusted == int(adjusted):
        adjusted = int(adjusted)

    thresholds = {"easy": 0, "medium": 0, "hard": 0, "deadly": 0}
    try:
        for member in party:
            level = int(member["level"])
            if level not in LEVEL_THRESHOLDS:
                return _bad_request("unsupported level")
            for key, value in LEVEL_THRESHOLDS[level].items():
                thresholds[key] += value
    except (KeyError, TypeError, ValueError):
        return _bad_request("invalid party member")

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
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return _bad_request("invalid body")
    combatants = body.get("combatants")
    if not isinstance(combatants, list):
        return _bad_request("invalid body")

    entries = []
    try:
        for combatant in combatants:
            name = combatant["name"]
            if not isinstance(name, str):
                return _bad_request("invalid name")
            dex = int(combatant["dex"])
            roll = int(combatant["roll"])
            entries.append({"name": name, "dex": dex, "score": roll + dex})
    except (KeyError, TypeError, ValueError):
        return _bad_request("invalid combatant")

    entries.sort(key=lambda e: (-e["score"], -e["dex"], e["name"]))
    order = [{"name": e["name"], "score": e["score"]} for e in entries]
    return jsonify(order=order)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ["PORT"]))
