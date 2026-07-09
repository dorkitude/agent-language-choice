import os
import re

from flask import Flask, jsonify, request

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

DICE_RE = re.compile(r"^(\d+)d(\d+)([+-]\d+)?$")


def multiplier_for_count(n):
    if n == 1:
        return 1
    if n == 2:
        return 1.5
    if 3 <= n <= 6:
        return 2
    if 7 <= n <= 10:
        return 2.5
    if 11 <= n <= 14:
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

    dice_min = count * 1 + modifier
    dice_max = count * sides + modifier
    average = (count * (sides + 1) / 2) + modifier
    if average == int(average):
        average = int(average)

    return jsonify(
        dice_count=count,
        sides=sides,
        modifier=modifier,
        min=dice_min,
        max=dice_max,
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
    for m in monsters:
        cr = str(m.get("cr"))
        count = m.get("count", 0)
        if cr not in CR_XP:
            return jsonify(error="unsupported cr"), 400
        base_xp += CR_XP[cr] * count
        monster_count += count

    multiplier = multiplier_for_count(monster_count)
    adjusted = base_xp * multiplier

    thresholds = {"easy": 0, "medium": 0, "hard": 0, "deadly": 0}
    for member in party:
        level = member.get("level")
        if level not in LEVEL_THRESHOLDS:
            return jsonify(error="unsupported level"), 400
        for key in thresholds:
            thresholds[key] += LEVEL_THRESHOLDS[level][key]

    difficulty = "trivial"
    if adjusted >= thresholds["deadly"]:
        difficulty = "deadly"
    elif adjusted >= thresholds["hard"]:
        difficulty = "hard"
    elif adjusted >= thresholds["medium"]:
        difficulty = "medium"
    elif adjusted >= thresholds["easy"]:
        difficulty = "easy"

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
    combatants = data.get("combatants", [])

    scored = []
    for c in combatants:
        score = c["roll"] + c["dex"]
        scored.append({"name": c["name"], "dex": c["dex"], "score": score})

    scored.sort(key=lambda c: (-c["score"], -c["dex"], c["name"]))

    order = [{"name": c["name"], "score": c["score"]} for c in scored]

    return jsonify(order=order)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ["PORT"]))
