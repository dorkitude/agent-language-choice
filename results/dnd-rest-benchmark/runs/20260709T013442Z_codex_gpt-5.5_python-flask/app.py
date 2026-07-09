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

DICE_PATTERN = re.compile(r"^([0-9]+)d([0-9]+)(?:([+-])([0-9]+))?$")


def json_body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ValueError("expected JSON object")
    return data


def bad_request(message="bad request"):
    return jsonify(error=message), 400


def monster_multiplier(count):
    if count <= 0:
        raise ValueError("monster count must be positive")
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


def compact_number(value):
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


@app.get("/health")
def health():
    return jsonify(ok=True)


@app.post("/v1/dice/stats")
def dice_stats():
    try:
        expression = json_body()["expression"]
        if not isinstance(expression, str):
            raise ValueError("expression must be a string")
        match = DICE_PATTERN.fullmatch(expression)
        if not match:
            raise ValueError("invalid expression")

        count = int(match.group(1))
        sides = int(match.group(2))
        if count <= 0 or sides <= 0:
            raise ValueError("count and sides must be positive")

        modifier = int(match.group(4) or 0)
        if match.group(3) == "-":
            modifier = -modifier

        return jsonify(
            dice_count=count,
            sides=sides,
            modifier=modifier,
            min=count + modifier,
            max=count * sides + modifier,
            average=compact_number(count * (sides + 1) / 2 + modifier),
        )
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid dice expression")


@app.post("/v1/checks/ability")
def ability_check():
    try:
        data = json_body()
        roll = data["roll"]
        modifier = data["modifier"]
        dc = data["dc"]
        if not all(isinstance(value, int) for value in (roll, modifier, dc)):
            raise ValueError("roll, modifier, and dc must be integers")

        total = roll + modifier
        return jsonify(total=total, success=total >= dc, margin=total - dc)
    except (KeyError, ValueError):
        return bad_request("invalid ability check")


@app.post("/v1/encounters/adjusted-xp")
def adjusted_xp():
    try:
        data = json_body()
        party = data["party"]
        monsters = data["monsters"]
        if not isinstance(party, list) or not isinstance(monsters, list):
            raise ValueError("party and monsters must be lists")

        thresholds = {"easy": 0, "medium": 0, "hard": 0, "deadly": 0}
        for member in party:
            if not isinstance(member, dict) or not isinstance(member.get("level"), int):
                raise ValueError("invalid party member")
            member_thresholds = LEVEL_THRESHOLDS[member["level"]]
            for key in thresholds:
                thresholds[key] += member_thresholds[key]

        base_xp = 0
        monster_count = 0
        for monster in monsters:
            if not isinstance(monster, dict):
                raise ValueError("invalid monster")
            cr = monster["cr"]
            count = monster["count"]
            if cr not in CR_XP or not isinstance(count, int) or count <= 0:
                raise ValueError("invalid monster")
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
            multiplier=multiplier,
            adjusted_xp=compact_number(adjusted),
            difficulty=difficulty,
            thresholds=thresholds,
        )
    except (KeyError, TypeError, ValueError):
        return bad_request("invalid encounter")


@app.post("/v1/initiative/order")
def initiative_order():
    try:
        combatants = json_body()["combatants"]
        if not isinstance(combatants, list):
            raise ValueError("combatants must be a list")

        entries = []
        for combatant in combatants:
            if not isinstance(combatant, dict):
                raise ValueError("invalid combatant")
            name = combatant["name"]
            dex = combatant["dex"]
            roll = combatant["roll"]
            if not isinstance(name, str) or not isinstance(dex, int) or not isinstance(roll, int):
                raise ValueError("invalid combatant")
            entries.append({"name": name, "dex": dex, "score": roll + dex})

        entries.sort(key=lambda item: (-item["score"], -item["dex"], item["name"]))
        return jsonify(order=[{"name": item["name"], "score": item["score"]} for item in entries])
    except (KeyError, ValueError):
        return bad_request("invalid initiative")


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ["PORT"]))
