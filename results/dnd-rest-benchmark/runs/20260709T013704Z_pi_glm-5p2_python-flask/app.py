from flask import Flask, jsonify, request
import os
import re

app = Flask(__name__)

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

# Per-level encounter thresholds: easy / medium / hard / deadly.
LEVEL_THRESHOLDS = {
    3: {"easy": 75, "medium": 150, "hard": 225, "deadly": 400},
}

DICE_RE = re.compile(r"(\d+)d(\d+)(?:([+-])(\d+))?")


def _norm(x):
    """Collapse whole floats to int (e.g. 10.0 -> 10) for cleaner JSON."""
    if isinstance(x, float) and x.is_integer():
        return int(x)
    return x


def _multiplier(count):
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


@app.get("/health")
def health():
    return jsonify(ok=True)


@app.post("/v1/dice/stats")
def dice_stats():
    data = request.get_json(force=True, silent=True)
    if not isinstance(data, dict):
        return jsonify(error="invalid body"), 400
    expression = data.get("expression")
    if not isinstance(expression, str):
        return jsonify(error="invalid expression"), 400
    m = DICE_RE.fullmatch(expression)
    if not m:
        return jsonify(error="invalid expression"), 400
    count = int(m.group(1))
    sides = int(m.group(2))
    if count <= 0 or sides <= 0:
        return jsonify(error="invalid expression"), 400
    if m.group(3):
        mod_val = int(m.group(4))
        modifier = mod_val if m.group(3) == "+" else -mod_val
    else:
        modifier = 0
    min_val = count + modifier
    max_val = count * sides + modifier
    average = (min_val + max_val) / 2
    return jsonify(
        dice_count=count,
        sides=sides,
        modifier=modifier,
        min=min_val,
        max=max_val,
        average=_norm(average),
    )


@app.post("/v1/checks/ability")
def ability_check():
    data = request.get_json(force=True, silent=True)
    if not isinstance(data, dict):
        return jsonify(error="invalid body"), 400
    try:
        roll = data["roll"]
        modifier = data["modifier"]
        dc = data["dc"]
    except KeyError:
        return jsonify(error="missing field"), 400
    total = roll + modifier
    return jsonify(total=total, success=total >= dc, margin=total - dc)


@app.post("/v1/encounters/adjusted-xp")
def adjusted_xp():
    data = request.get_json(force=True, silent=True)
    if not isinstance(data, dict):
        return jsonify(error="invalid body"), 400
    party = data.get("party", [])
    monsters = data.get("monsters", [])

    base_xp = 0
    monster_count = 0
    for mon in monsters:
        cr = mon["cr"]
        c = mon["count"]
        if cr not in XP_TABLE:
            return jsonify(error="unsupported cr"), 400
        base_xp += XP_TABLE[cr] * c
        monster_count += c

    mult = _multiplier(monster_count)
    adjusted = _norm(base_xp * mult)

    thresholds = {"easy": 0, "medium": 0, "hard": 0, "deadly": 0}
    for member in party:
        level = member["level"]
        if level not in LEVEL_THRESHOLDS:
            return jsonify(error="unsupported level"), 400
        for k in thresholds:
            thresholds[k] += LEVEL_THRESHOLDS[level][k]

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
        multiplier=_norm(mult),
        adjusted_xp=adjusted,
        difficulty=difficulty,
        thresholds=thresholds,
    )


@app.post("/v1/initiative/order")
def initiative_order():
    data = request.get_json(force=True, silent=True)
    if not isinstance(data, dict):
        return jsonify(error="invalid body"), 400
    combatants = data.get("combatants", [])
    scored = []
    for c in combatants:
        scored.append(
            {"name": c["name"], "score": c["roll"] + c["dex"], "dex": c["dex"]}
        )
    scored.sort(key=lambda x: (-x["score"], -x["dex"], x["name"]))
    order = [{"name": x["name"], "score": x["score"]} for x in scored]
    return jsonify(order=order)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ["PORT"]))
