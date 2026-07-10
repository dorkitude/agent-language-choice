import os
import re

from flask import Flask, jsonify, request

app = Flask(__name__)

# --- D&D data tables ---------------------------------------------------------

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

# Per-level encounter thresholds: easy, medium, hard, deadly.
LEVEL_THRESHOLDS = {
    3: {"easy": 75, "medium": 150, "hard": 225, "deadly": 400},
}

# Monster-count -> encounter multiplier.
def multiplier_for(count: int) -> float:
    if count <= 1:
        return 1
    if count == 2:
        return 1.5
    if 3 <= count <= 6:
        return 2
    if 7 <= count <= 10:
        return 2.5
    if 11 <= count <= 14:
        return 3
    return 4  # 15+

# Whole-valued floats -> int, so JSON renders "10" not "10.0".
def norm(x):
    if isinstance(x, float) and x.is_integer():
        return int(x)
    return x

# --- helpers -----------------------------------------------------------------

DICE_RE = re.compile(r"^([1-9]\d*)d([1-9]\d*)(?:([+-])(\d+))?$")


def get_body():
    """Parse the request body as JSON, returning None when invalid/missing."""
    return request.get_json(force=True, silent=True)


def bad(msg="bad request"):
    return jsonify({"error": msg}), 400


def is_int(v):
    """True for genuine ints (JSON bools are excluded)."""
    return isinstance(v, int) and not isinstance(v, bool)


# --- routes ------------------------------------------------------------------

@app.get("/health")
def health():
    return jsonify(ok=True)


@app.post("/v1/dice/stats")
def dice_stats():
    body = get_body()
    if not isinstance(body, dict):
        return bad("invalid body")
    expression = body.get("expression")
    if not isinstance(expression, str):
        return bad("invalid expression")
    m = DICE_RE.match(expression.strip())
    if not m:
        return bad("invalid expression")
    count = int(m.group(1))
    sides = int(m.group(2))
    if m.group(3):
        modifier = int(m.group(3) + m.group(4))
    else:
        modifier = 0
    min_val = count * 1 + modifier
    max_val = count * sides + modifier
    average = (min_val + max_val) / 2
    return jsonify(
        dice_count=count,
        sides=sides,
        modifier=modifier,
        min=min_val,
        max=max_val,
        average=norm(average),
    )


@app.post("/v1/checks/ability")
def ability_check():
    body = get_body()
    if not isinstance(body, dict):
        return bad("invalid body")
    roll = body.get("roll")
    modifier = body.get("modifier")
    dc = body.get("dc")
    if not all(isinstance(v, int) and not isinstance(v, bool) for v in (roll, modifier, dc)):
        return bad("invalid fields")
    total = roll + modifier
    success = total >= dc
    margin = total - dc
    return jsonify(total=total, success=success, margin=margin)


@app.post("/v1/encounters/adjusted-xp")
def adjusted_xp():
    body = get_body()
    if not isinstance(body, dict):
        return bad("invalid body")
    party = body.get("party")
    monsters = body.get("monsters")
    if not isinstance(party, list) or not isinstance(monsters, list):
        return bad("invalid fields")

    base_xp = 0
    monster_count = 0
    for mon in monsters:
        if not isinstance(mon, dict):
            return bad("invalid monster")
        cr = mon.get("cr")
        count = mon.get("count")
        if not isinstance(cr, str) or cr not in CR_XP:
            return bad("invalid cr")
        if not isinstance(count, int) or isinstance(count, bool) or count < 1:
            return bad("invalid count")
        base_xp += CR_XP[cr] * count
        monster_count += count

    mult = multiplier_for(monster_count)
    adjusted = base_xp * mult

    # Sum thresholds across party members (level-3 supported; fallback to 3).
    thresholds = {"easy": 0, "medium": 0, "hard": 0, "deadly": 0}
    for member in party:
        if not isinstance(member, dict):
            return bad("invalid party member")
        level = member.get("level")
        if not isinstance(level, int) or isinstance(level, bool):
            return bad("invalid level")
        row = LEVEL_THRESHOLDS.get(level, LEVEL_THRESHOLDS[3])
        for k in thresholds:
            thresholds[k] += row[k]

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
        multiplier=norm(mult),
        adjusted_xp=norm(adjusted),
        difficulty=difficulty,
        thresholds=thresholds,
    )


@app.post("/v1/initiative/order")
def initiative_order():
    body = get_body()
    if not isinstance(body, dict):
        return bad("invalid body")
    combatants = body.get("combatants")
    if not isinstance(combatants, list):
        return bad("invalid combatants")

    scored = []
    for c in combatants:
        if not isinstance(c, dict):
            return bad("invalid combatant")
        name = c.get("name")
        dex = c.get("dex")
        roll = c.get("roll")
        if not isinstance(name, str):
            return bad("invalid name")
        if not isinstance(dex, int) or isinstance(dex, bool):
            return bad("invalid dex")
        if not isinstance(roll, int) or isinstance(roll, bool):
            return bad("invalid roll")
        scored.append({"name": name, "dex": dex, "score": roll + dex})

    # score desc, dex desc, name asc.
    scored.sort(key=lambda c: (-c["score"], -c["dex"], c["name"]))
    order = [{"name": c["name"], "score": c["score"]} for c in scored]
    return jsonify(order=order)


# --- character rules ---------------------------------------------------------

ABILITY_KEYS = ("str", "dex", "con", "int", "wis", "cha")


def ability_modifier(score: int) -> int:
    # floor((score - 10) / 2); Python // floors toward -inf, so 9 -> -1.
    return (score - 10) // 2


def proficiency_bonus(level: int) -> int:
    # Tiers of 4: 1-4 -> 2, 5-8 -> 3, ..., 17-20 -> 6.
    return 2 + (level - 1) // 4


@app.post("/v1/characters/ability-modifier")
def character_ability_modifier():
    body = get_body()
    if not isinstance(body, dict):
        return bad("invalid body")
    score = body.get("score")
    if not is_int(score) or not (1 <= score <= 30):
        return bad("invalid score")
    return jsonify(score=score, modifier=ability_modifier(score))


@app.post("/v1/characters/proficiency")
def character_proficiency():
    body = get_body()
    if not isinstance(body, dict):
        return bad("invalid body")
    level = body.get("level")
    if not is_int(level) or not (1 <= level <= 20):
        return bad("invalid level")
    return jsonify(level=level, proficiency_bonus=proficiency_bonus(level))


@app.post("/v1/characters/derived-stats")
def character_derived_stats():
    body = get_body()
    if not isinstance(body, dict):
        return bad("invalid body")
    level = body.get("level")
    if not is_int(level) or not (1 <= level <= 20):
        return bad("invalid level")
    abilities = body.get("abilities")
    if not isinstance(abilities, dict):
        return bad("invalid abilities")
    modifiers = {}
    for key in ABILITY_KEYS:
        score = abilities.get(key)
        if not is_int(score) or not (1 <= score <= 30):
            return bad("invalid ability %s" % key)
        modifiers[key] = ability_modifier(score)
    armor = body.get("armor")
    if not isinstance(armor, dict):
        return bad("invalid armor")
    base = armor.get("base")
    dex_cap = armor.get("dex_cap")
    shield = armor.get("shield")
    if not is_int(base):
        return bad("invalid armor base")
    if not is_int(dex_cap):
        return bad("invalid armor dex_cap")
    if not isinstance(shield, bool):
        return bad("invalid armor shield")
    shield_bonus = 2 if shield else 0
    armor_class = base + min(modifiers["dex"], dex_cap) + shield_bonus
    hp_max = level * (6 + modifiers["con"])
    return jsonify(
        level=level,
        proficiency_bonus=proficiency_bonus(level),
        hp_max=hp_max,
        armor_class=armor_class,
        modifiers=modifiers,
    )


# --- combat state ------------------------------------------------------------

# In-memory combat sessions: id -> session dict.
COMBAT_SESSIONS = {}


def _session_or_404(sid):
    session = COMBAT_SESSIONS.get(sid)
    if session is None:
        return None, (jsonify({"error": "unknown session"}), 404)
    return session, None


@app.post("/v1/combat/sessions")
def create_combat_session():
    body = get_body()
    if not isinstance(body, dict):
        return bad("invalid body")
    sid = body.get("id")
    if not isinstance(sid, str) or not sid:
        return bad("invalid id")
    combatants = body.get("combatants")
    if not isinstance(combatants, list) or not combatants:
        return bad("invalid combatants")
    scored = []
    for c in combatants:
        if not isinstance(c, dict):
            return bad("invalid combatant")
        name = c.get("name")
        dex = c.get("dex")
        roll = c.get("roll")
        if not isinstance(name, str) or not name:
            return bad("invalid name")
        if not is_int(dex):
            return bad("invalid dex")
        if not is_int(roll):
            return bad("invalid roll")
        scored.append({"name": name, "dex": dex, "score": roll + dex})
    # score desc, dex desc, name asc.
    scored.sort(key=lambda c: (-c["score"], -c["dex"], c["name"]))
    session = {
        "id": sid,
        "round": 1,
        "turn_index": 0,
        "order": scored,
        "conditions": {},  # name -> list of {condition, remaining_rounds}
    }
    COMBAT_SESSIONS[sid] = session
    active = {"name": scored[0]["name"], "score": scored[0]["score"]}
    return jsonify(
        id=sid,
        round=1,
        turn_index=0,
        active=active,
        order=[{"name": c["name"], "score": c["score"]} for c in scored],
    )


@app.post("/v1/combat/sessions/<sid>/conditions")
def add_condition(sid):
    session, err = _session_or_404(sid)
    if err is not None:
        return err
    body = get_body()
    if not isinstance(body, dict):
        return bad("invalid body")
    target = body.get("target")
    condition = body.get("condition")
    duration = body.get("duration_rounds")
    names = [c["name"] for c in session["order"]]
    if not isinstance(target, str) or target not in names:
        return bad("invalid target")
    if not isinstance(condition, str) or not condition:
        return bad("invalid condition")
    if not is_int(duration) or duration <= 0:
        return bad("invalid duration_rounds")
    conds = session["conditions"].setdefault(target, [])
    conds.append({"condition": condition, "remaining_rounds": duration})
    return jsonify(
        target=target,
        conditions=[
            {"condition": c["condition"], "remaining_rounds": c["remaining_rounds"]}
            for c in conds
        ],
    )


@app.post("/v1/combat/sessions/<sid>/advance")
def advance_combat(sid):
    session, err = _session_or_404(sid)
    if err is not None:
        return err
    order = session["order"]
    n = len(order)
    idx = session["turn_index"] + 1
    if idx >= n:
        idx = 0
        session["round"] += 1
    session["turn_index"] = idx
    active = order[idx]
    # At the start of the active combatant's turn, decrement their conditions.
    name = active["name"]
    conds = session["conditions"].get(name, [])
    kept = []
    for c in conds:
        c["remaining_rounds"] -= 1
        if c["remaining_rounds"] > 0:
            kept.append(c)
    if kept:
        session["conditions"][name] = kept
    else:
        session["conditions"].pop(name, None)
    # Build conditions response in initiative order (only non-empty).
    conditions_resp = {}
    for c in order:
        clist = session["conditions"].get(c["name"])
        if clist:
            conditions_resp[c["name"]] = [
                {"condition": cc["condition"], "remaining_rounds": cc["remaining_rounds"]}
                for cc in clist
            ]
    return jsonify(
        id=session["id"],
        round=session["round"],
        turn_index=session["turn_index"],
        active={"name": active["name"], "score": active["score"]},
        conditions=conditions_resp,
    )


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ["PORT"]))
