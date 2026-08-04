"""Health check, dice, ability checks, encounter XP, and initiative order."""

from flask import Blueprint, jsonify, request

from ..rules import classify_difficulty, multiplier_for_count, sum_party_thresholds, CR_XP
from ..validation import DICE_RE

bp = Blueprint("core", __name__)


@bp.get("/health")
def health():
    return jsonify(ok=True)


@bp.post("/v1/dice/stats")
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

    min_val = count * 1 + modifier
    max_val = count * sides + modifier
    average_raw = (count * (sides + 1) / 2) + modifier
    average = int(average_raw) if average_raw == int(average_raw) else average_raw

    return jsonify(
        dice_count=count,
        sides=sides,
        modifier=modifier,
        min=min_val,
        max=max_val,
        average=average,
    )


@bp.post("/v1/checks/ability")
def ability_check():
    data = request.get_json(silent=True) or {}
    try:
        roll = data["roll"]
        modifier = data["modifier"]
        dc = data["dc"]
    except KeyError:
        return jsonify(error="missing fields"), 400

    if not all(isinstance(v, (int, float)) for v in (roll, modifier, dc)):
        return jsonify(error="invalid fields"), 400

    total = roll + modifier
    success = total >= dc
    margin = total - dc

    return jsonify(total=total, success=success, margin=margin)


@bp.post("/v1/encounters/adjusted-xp")
def adjusted_xp():
    data = request.get_json(silent=True) or {}
    party = data.get("party")
    monsters = data.get("monsters")

    if not isinstance(party, list) or not isinstance(monsters, list):
        return jsonify(error="invalid request"), 400

    try:
        base_xp = 0
        monster_count = 0
        for monster in monsters:
            cr = str(monster["cr"])
            count = int(monster["count"])
            if cr not in CR_XP:
                return jsonify(error="unsupported cr"), 400
            base_xp += CR_XP[cr] * count
            monster_count += count

        thresholds_sum = sum_party_thresholds(party)
        if thresholds_sum is None:
            return jsonify(error="unsupported level"), 400
    except (KeyError, TypeError, ValueError):
        return jsonify(error="invalid request"), 400

    multiplier = multiplier_for_count(monster_count)
    adjusted = base_xp * multiplier
    difficulty = classify_difficulty(adjusted, thresholds_sum)

    return jsonify(
        base_xp=base_xp,
        monster_count=monster_count,
        multiplier=multiplier,
        adjusted_xp=adjusted,
        difficulty=difficulty,
        thresholds=thresholds_sum,
    )


@bp.post("/v1/initiative/order")
def initiative_order():
    data = request.get_json(silent=True) or {}
    combatants = data.get("combatants")
    if not isinstance(combatants, list):
        return jsonify(error="invalid request"), 400

    try:
        scored = []
        for c in combatants:
            name = c["name"]
            dex = c["dex"]
            roll = c["roll"]
            score = roll + dex
            scored.append({"name": name, "dex": dex, "score": score})
    except (KeyError, TypeError):
        return jsonify(error="invalid request"), 400

    scored.sort(key=lambda c: (-c["score"], -c["dex"], c["name"]))

    order = [{"name": c["name"], "score": c["score"]} for c in scored]

    return jsonify(order=order)
