from flask import Flask, jsonify, request
import os
import re

app = Flask(__name__)

DICE_RE = re.compile(r"^(\d+)d(\d+)(?:\+(\d+)|-(\d+))?$")

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

THRESHOLDS = {
    3: {"easy": 75, "medium": 150, "hard": 225, "deadly": 400},
}


def monster_multiplier(count):
    if count == 1:
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


@app.get("/health")
def health():
    return jsonify(ok=True)


@app.post("/v1/dice/stats")
def dice_stats():
    data = request.get_json(silent=True) or {}
    expr = data.get("expression")
    match = DICE_RE.match(str(expr)) if expr is not None else None
    if not match:
        return jsonify(error="invalid expression"), 400

    count_str, sides_str, plus, minus = match.groups()
    count = int(count_str)
    sides = int(sides_str)
    if count <= 0 or sides <= 0:
        return jsonify(error="invalid expression"), 400

    if plus:
        modifier = int(plus)
    elif minus:
        modifier = -int(minus)
    else:
        modifier = 0

    minimum = count + modifier
    maximum = count * sides + modifier
    average = count * (sides + 1) / 2 + modifier
    if isinstance(average, float) and average.is_integer():
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
        roll = int(data["roll"])
        modifier = int(data["modifier"])
        dc = int(data["dc"])
    except Exception:
        return jsonify(error="invalid input"), 400

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
        xp = CR_XP.get(cr)
        if xp is None:
            return jsonify(error="unsupported cr"), 400
        base_xp += xp * count
        monster_count += count

    multiplier = monster_multiplier(monster_count)
    adjusted = base_xp * multiplier

    thresholds = {"easy": 0, "medium": 0, "hard": 0, "deadly": 0}
    for member in party:
        level = member.get("level")
        level_thresholds = THRESHOLDS.get(level)
        if level_thresholds is None:
            return jsonify(error="unsupported level"), 400
        for key in thresholds:
            thresholds[key] += level_thresholds[key]

    if adjusted >= thresholds["deadly"]:
        difficulty = "deadly"
    elif adjusted >= thresholds["hard"]:
        difficulty = "hard"
    elif adjusted >= thresholds["medium"]:
        difficulty = "medium"
    elif adjusted >= thresholds["easy"]:
        difficulty = "easy"
    else:
        difficulty = "trivial"

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

    scored = [
        {
            "name": c["name"],
            "dex": c["dex"],
            "score": c["roll"] + c["dex"],
        }
        for c in combatants
    ]
    scored.sort(key=lambda c: (-c["score"], -c["dex"], c["name"]))

    return jsonify(order=[{"name": c["name"], "score": c["score"]} for c in scored])


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ["PORT"]))
